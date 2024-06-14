from django.shortcuts import render
from django.http import JsonResponse
import pandas as pd
from .utils import get_hourly_eia_net_demand_and_generation, get_hourly_eia_interchange, get_hourly_eia_grid_mix
from .utils import compute_hourly_consumption_by_source_ba, compute_hourly_fuel_mix_after_import_export, cache_wrapped_hourly_gen_mix_by_ba_and_type
from .utils import cache_wrapped_co2_boxplot_all_bas
from .utils import get_historical_solar_weather, get_historical_window_irradiance, HomeCharacteristics, model_one_house
from .utils import combine_house_simulation_with_co2_intensity, fix_timestamp_index
import datetime
import json
import re


def index(request):
    context = {}
    return render(request, "load_shifting/pie.html", context)


def energy_mix_json(request):
    # TODO add some UI to choose BA and year.

    ba = request.GET.get("ba") or "CISO"
    year = int( request.GET.get("year") or "2024" )
    
    print("Querying for ba= {} and year = {}".format(ba, year))
    start_date = datetime.datetime(year=year, month=4, day=1)
    end_date = datetime.datetime(year=year, month=4, day=30)

    hourly_usage = get_hourly_eia_grid_mix([ba], start_date = start_date, end_date = end_date)
    hourly_usage["hour"] = pd.to_datetime(hourly_usage.period, format="ISO8601").apply(lambda x: x.hour)
    print(hourly_usage["type-name"].unique())

    # TODO: cache this data frame!!

    usage_by_clock_hour = pd.DataFrame(data = {
        "hour": hourly_usage.hour,
        "fuel": hourly_usage["type-name"],
        "mwh": hourly_usage["Generation (MWh)"]
    }).groupby(["hour", "fuel"]).aggregate("sum").reset_index()

    # Convert data frame to the JSON format expected by D3.js:
    json_data_series = []
    for hour in usage_by_clock_hour["hour"].unique():
        sub_frame = usage_by_clock_hour[ usage_by_clock_hour["hour"] == hour ]
        json_data_series.append(
            {"key": "Hour = {}".format(hour),
             "values": sub_frame.to_dict("records")})

    
    return JsonResponse({"data_series": json_data_series})


def co2_intensity(request):
    context = {}
    return render(request, "load_shifting/co2.html", context)


def co2_intensity_by_clock_hour(usage_df):
    # Group df by hour, not caring about source BA, sum up emissions and divide by kwh
    # to get a data frame of hourly tons-co2-per-kwh
    corrected_intensity_by_hour = usage_df[["Usage (MWh)", "emissions", "timestamp"]].groupby(
        ["timestamp"]).aggregate("sum").reset_index()

    corrected_intensity_by_hour["pounds_co2_per_kwh"] = corrected_intensity_by_hour["emissions"] / (corrected_intensity_by_hour["Usage (MWh)"]*1000)

    # Reduce to one data point per clock hour (e.g. avg of all 1-ams, avgs of all 2-ams, etc.)
    corrected_intensity_by_hour["hour"] = pd.to_datetime(corrected_intensity_by_hour.timestamp).apply(lambda x: x.hour)

    # Note we get different results here depending on whether we treat this avg as "all hours weighted equally" (current behavior)
    # vs "all kwh weighted equally" (big kwh days matter more)
    intensity_by_clock_hour = corrected_intensity_by_hour[["hour", "pounds_co2_per_kwh"]].groupby(["hour"]).aggregate("mean").reset_index()
    return intensity_by_clock_hour


    
def co2_intensity_json(request):
    # TODO get these 3 from the request:
    ba = "CISO"
    start_date = datetime.datetime(year=2024, month=4, day=1)
    end_date = datetime.datetime(year=2024, month=4, day=30)
    
    usage_df = cache_wrapped_hourly_gen_mix_by_ba_and_type(
        ba_name=ba,
        start_date=start_date,
        end_date=end_date)

    intensity_by_clock_hour = co2_intensity_by_clock_hour(usage_df)
    json_data_series = intensity_by_clock_hour.to_dict("records")
    return JsonResponse({"ba_stats": json_data_series})



def co2_intensity_boxplot(request):
    context = {}
    return render(request, "load_shifting/boxplot.html", context)


def co2_intensity_boxplot_json(request):
    #with open("load_shifting/list_of_all_bas.txt", "r") as ba_file:
    #    ba_text = ba_file.read()
    #    all_of_bas = re.findall(r'\((\w+)\)', ba_text)
    biggest_bas = ["CISO", "SWPP", "ERCO", "MISO", "TVA", "SOCO", "PJM", "NYIS", "ISNE"]
    start_date = datetime.datetime(year=2024, month=4, day=1)
    end_date = datetime.datetime(year=2024, month=4, day=30)

    df = cache_wrapped_co2_boxplot_all_bas(
        ba_names = biggest_bas, # all_of_bas,
        start_date = start_date,
        end_date = end_date
    )

    json_data_series = df.to_dict("records")
    return JsonResponse({"ba_stats": json_data_series})
    # need a special cache for this cuz it gonna be expensive to calculate
    # but instead of writing a new cache for everything, make a general-purpose cache table


def home_simulation_json(request):
    #building_latitude, building_longitude = 37.566504300139655, -122.37997055249495
    # Nueva school

    # jeffersonville vermont lat/lon: 44.64536116761554, -72.82704009279546
    building_latitude, building_longitude = 44.64536116761554, -72.82704009279546

    old_home = HomeCharacteristics(
        latitude = building_latitude, #36.1248871, # Las Vegas, NV
        longitude = building_longitude, #-115.3398063, # Las Vegas, NV

        ## HVAC temperature setpoints (i.e. your thermostat settings)
        # Your HVAC system will start heating your home if the indoor temperature is below HEATING_SETPOINT_C (house is too cold)
        # It will start cooling your home if the indoor temperature is above COOLING_SETPOINT_C (house is too warm)
        heating_setpoint_c=20, # ~65f
        cooling_setpoint_c=22, # ~75f

        ## HVAC system characteristics
        hvac_capacity_w=10000,
        # Different types of HVAC systems have different efficiencies (note: this is a hand-wavy approximation):
        #  - Old boiler with uninsulated pipes = ~0.5
        #  - Electric radiator = ~1
        #  - High-efficiency heat pump = ~4 (how can this be higher than 1?? heat pumpts are magical..) 
        hvac_overall_system_efficiency=1,

        ## Home dimensions
        # Note: these are in SI units. If you're used to Imperial: one square meter is 10.7639 sq. ft
        conditioned_floor_area_sq_m=200, # ~2200 sqft
        ceiling_height_m=3, # 10ft ceilings (pretty tall)

        ## Wall Insulation
        # R value (SI): temperature difference (K) required to create 1 W/m2 of heat flux through a surface. Higher = better insulated
        wall_insulation_r_value_imperial=11, # Imperial units: ft^2 °F/Btu

        ## Air changes per hour at 50 pascals.
        # This is a measure of the "leakiness" of the home: 3 is pretty tight, A "passive house" is < 0.6
        # This number is measured in a "blower door test", which pressurizes the home to 50 pascals
        ach50=10,

        ## Window area
        # We're only modeling South-facing windows, as they have the largest effect from solar irradiance (in the Northern hemisphere)
        # We're assuming the window has an R value matching the walls (so we don't have to model it separately)
        # Change the line below to roughly match the size of your south-facing windows
        south_facing_window_size_sq_m=10, # ~110 sq ft
        # Solar Heat Gain Coefficient (SHGC) is a ratio of how much of the sun's energy makes it through the window (0-1)
        # Different types of windows have different values, e.g. a Double-pane, Low-E, H-Gain window SHGC=0.56
        window_solar_heat_gain_coefficient=0.5,

        # First version of model assumed solar energy always comes in the window even when unwanted.
        can_close_curtains = False,
        smart_hvac_algorithm = False
    )

    new_home = HomeCharacteristics(
        latitude = building_latitude, #36.1248871, # Las Vegas, NV
        longitude = building_longitude, #-115.3398063, # Las Vegas, NV

        ## HVAC temperature setpoints (i.e. your thermostat settings)
        heating_setpoint_c=20, # ~65f
        cooling_setpoint_c=22, # ~75f
        # can try making the heating setpoint colder and cooling setpoint hotter for smart home

        ## HVAC system characteristics
        hvac_capacity_w=10000,
        # Different types of HVAC systems have different efficiencies (note: this is a hand-wavy approximation):
        #  - Old boiler with uninsulated pipes = ~0.5
        #  - Electric radiator = ~1
        #  - High-efficiency heat pump = ~4 (how can this be higher than 1?? heat pumpts are magical..) 
        hvac_overall_system_efficiency=2.0,
        
        ## Home dimensions
        # Note: these are in SI units. If you're used to Imperial: one square meter is 10.7639 sq. ft
        conditioned_floor_area_sq_m=200, # ~2200 sqft
        ceiling_height_m=3, # 10ft ceilings (pretty tall)
        
        ## Wall Insulation
        # R value (SI): temperature difference (K) required to create 1 W/m2 of heat flux through a surface. Higher = better insulated
        wall_insulation_r_value_imperial=27,
        ach50=1.5,
        # can be as low as 0.6, from https://en.wikipedia.org/wiki/Passive_house#Superinsulation
        south_facing_window_size_sq_m=10,
        window_solar_heat_gain_coefficient=0.5,
        can_close_curtains = True,
        smart_hvac_algorithm = False
    )

    smart_home = HomeCharacteristics(
        latitude = building_latitude,
        longitude = building_longitude,
        heating_setpoint_c=19, #20, # ~65f
        cooling_setpoint_c=23, #22, # ~75f
        hvac_capacity_w=10000,
        hvac_overall_system_efficiency=2.0,
        
        ## Home dimensions
        # Note: these are in SI units. If you're used to Imperial: one square meter is 10.7639 sq. ft
        conditioned_floor_area_sq_m=200, # ~2200 sqft
        ceiling_height_m=3, # 10ft ceilings (pretty tall)
        
        ## Wall Insulation
        # R value (SI): temperature difference (K) required to create 1 W/m2 of heat flux through a surface. Higher = better insulated
        wall_insulation_r_value_imperial=27,
        ach50=1.5,
        # can be as low as 0.6, from https://en.wikipedia.org/wiki/Passive_house#Superinsulation
        south_facing_window_size_sq_m=10,
        window_solar_heat_gain_coefficient=0.5,
        can_close_curtains = True,
        smart_hvac_algorithm = True
    )
    
    start_date = datetime.datetime(year=2022, month=1, day=1)
    end_date = datetime.datetime(year=2022, month=12, day=31)
    
    historical_weather_2022 = get_historical_solar_weather(
        start_date = start_date,
        end_date = end_date,
        latitude = building_latitude, longitude = building_longitude)
    historical_weather_2022 = fix_timestamp_index(historical_weather_2022)
    
    window_irr_2022 = get_historical_window_irradiance(
        start_date = start_date,
        end_date = end_date,
        latitude = building_latitude, longitude = building_longitude)
    window_irr_2022 = fix_timestamp_index(window_irr_2022)
    historical_weather_2022 = historical_weather_2022.join(window_irr_2022)
    
    ba = "CISO" # TODO get from address or lat/lon.
    usage_df = cache_wrapped_hourly_gen_mix_by_ba_and_type(
        ba_name=ba,
        start_date=start_date,
        end_date=end_date)

    corrected_intensity_by_hour = usage_df[["Usage (MWh)", "emissions", "timestamp"]].groupby(
        ["timestamp"]).aggregate("sum").reset_index()

    corrected_intensity_by_hour["pounds_co2_per_kwh"] = corrected_intensity_by_hour["emissions"] / (corrected_intensity_by_hour["Usage (MWh)"]*1000)
    corrected_intensity_by_hour["timestamp"] = pd.to_datetime(corrected_intensity_by_hour.timestamp)

    # TODO: move consistency checks here.
    historical_weather_2022["timestamp_hour_no_tz"] = historical_weather_2022.apply(
        lambda row: datetime.datetime(year=int(row["Year"]), month=int(row["Month"]), day=int(row["Day"]), hour=int(row["Hour"])),
        axis=1
    )
    
    corrected_intensity_by_hour["timestamp_hour_no_tz"] = corrected_intensity_by_hour.timestamp.apply(
        lambda x: datetime.datetime(year=x.year, month=x.month, day=x.day, hour=x.hour)
    )

    weather_with_co2_2022 = historical_weather_2022.merge(corrected_intensity_by_hour, how="inner", on="timestamp_hour_no_tz")
    weather_with_co2_2022.set_index("timestamp", inplace=True)

    # TODO maybe make this a loop through an arbitrary number of houses:
    print("Simulating old house")
    old_house_simulation = model_one_house(
        old_home, weather_with_co2_2022)
    print("Old house total CO2 for year: {}".format( old_house_simulation["pounds_co2"].sum()))
    print("Simulating new house")
    new_house_simulation = model_one_house(
        new_home, weather_with_co2_2022)
    print("New house total CO2 for year: {}".format( new_house_simulation["pounds_co2"].sum()))
    print("Simulating smart house")
    smart_house_simulation = model_one_house(
        smart_home, weather_with_co2_2022)
    print("Smart house total CO2 for year: {}".format( smart_house_simulation["pounds_co2"].sum()))
    

    
    # columns = 
    #[temperature_difference_c', 'Conductive energy (J)',
    #   'Air change energy (J)', 'Radiant energy (J)', 'HVAC energy (J)',
    #   'hvac_mode', 'Net energy xfer', 'ΔT', 'Outdoor Temperature (C)',
    #   'Indoor Temperature (C)', 'HVAC energy use (kWh)', 'timestamp',
    #   'Usage (MWh)', 'emissions', 'pounds_co2_per_kwh', 'pounds_co2']

    # net energy xfer looks weird in the animation because i think it includes the
    # energy gain from running the hvac, and what i really want it to show is just
    # conductive + air change + radiant, but without hvac

    # would also be good to show a visualization of thermostat, i.e. temperature
    # relative to upper and lower bounds of thermostat settings

    # reshape into multiple data series, each with
    # key and values, each value having (timestamp, n)
    all_data_series = []


    # Transform timestamp object into a text format that Javascript can parse
    # into a Javascript date object.
    all_data_series.append({
        "key": "Timestamp",
        "values": [x for x in old_house_simulation.timestamp.apply(lambda x: x.strftime("%m-%d:%H")).values]
    })

    all_data_series.append({
        "key": "Outdoor Temperature (C)",
        "values": [x for x in old_house_simulation["Outdoor Temperature (C)"].values]
    })

    # I think that for X houses, we actually want say Indooor Temperature (C) to be
    # a list of tuples or dictionary - one data point for each house at that timestamp

    
    for col_name in ["Indoor Temperature (C)", "pounds_co2", "hvac_mode", "heat_xfer_from_outside"]:
        old_house_vals = [x for x in old_house_simulation[col_name].values]
        new_house_vals = [x for x in new_house_simulation[col_name].values]
        smart_house_vals = [x for x in smart_house_simulation[col_name].values]

        all_data_series.append(
            {"key": col_name,
             "values": list( zip(old_house_vals, new_house_vals, smart_house_vals) )})

    return JsonResponse({"house_simulation": all_data_series})



def home_simulation(request):
    context = { "debug": "" }
    return render(request, "load_shifting/home_simulation.html", context)

    # d3 viz that's something like... for each time slice change temp inside
    # house, change inflowing and outflowing heat arrows, change electricity
    # consumption arrow, change CO2 cloud size

    # 3 side-by-side viz: badly insulated house, well-insulated house,
    # well-insulated house with smart thermostat algorithm
    # each one builds up a cumulative CO2 cloud





