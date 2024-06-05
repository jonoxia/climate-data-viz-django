from django.shortcuts import render
from django.http import JsonResponse
import pandas as pd
from .utils import get_hourly_eia_net_demand_and_generation, get_hourly_eia_interchange, get_hourly_eia_grid_mix
from .utils import compute_hourly_consumption_by_source_ba, compute_hourly_fuel_mix_after_import_export, cache_wrapped_hourly_gen_mix_by_ba_and_type
from .utils import cache_wrapped_co2_boxplot_all_bas
from .utils import get_historical_solar_weather, get_historical_window_irradiance, HomeCharacteristics, model_one_house
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

def co2_intensity_json(request):
    # TODO get these 3 from the request:
    ba = "CISO"
    start_date = datetime.datetime(year=2024, month=4, day=1)
    end_date = datetime.datetime(year=2024, month=4, day=30)
    
    usage_df = cache_wrapped_hourly_gen_mix_by_ba_and_type(
        ba_name=ba,
        start_date=start_date,
        end_date=end_date)
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


def home_simulation(request):
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

    start_date = datetime.datetime(year=2022, month=1, day=1)
    end_date = datetime.datetime(year=2022, month=12, day=31)
    
    historical_weather_2022 = get_historical_solar_weather(
        start_date = start_date,
        end_date = end_date,
        latitude = building_latitude, longitude = building_longitude)

    window_irr_2022 = get_historical_window_irradiance(
        start_date = start_date,
        end_date = end_date,
        latitude = building_latitude,
        longitude = building_longitude)

    ba = "CISO" # TODO
    start_date = datetime.datetime(year=2024, month=4, day=1)
    end_date = datetime.datetime(year=2024, month=4, day=30)
    
    co2_intensity = cache_wrapped_hourly_gen_mix_by_ba_and_type(
        ba_name=ba,
        start_date=start_date,
        end_date=end_date)

    house_simulation = model_one_house(old_home, historical_weather_2022, window_irr_2022, co2_intensity)

    context = { "debug": house_simulation.head() }
    return render(request, "load_shifting/home_simulation.html", context)
