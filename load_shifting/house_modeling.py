
# Welcome to your second deep dive lab assignment!

# In this notebook, we're going to simulate the electricity usage of a home's HVAC system
# We're using a "baby energy model" that we're writing from scratch. This is a very simplistic model, so it's only factoring in:
#  - home envelope characteristics (e.g. dimensions, insulation, window area etc)
#  - HVAC (heating, venting, air conditioning) system characteristics
#  - historical weather data

# Out-of-scope
#  - other major energy consumers, like non-HVAC appliances (water heater, fridge, electronics, etc)
#  - non-electric energy usage (e.g. using natural gas for central heating)
#  - splitting heating and cooling into separate systems (we assume there is a single HVAC system that does both heating & cooling)

# We'll be involving a 3rd party library, called pvlib, to fetch the historical weather data and model solar irradiance


# model doesn't adequately predict cooling needs on sunny days? I bet that's because there's nothing that accounts for solar
# load on the building (apart from the window). TODO!



# In this cell, we're importing packages that we'll use later in the notebook
# You do not need to make changes to this cell.

# Before we can import it, we have to install the pvlib package to the notebook's python kernel
# Hex notebooks have some common 3rd party packages already installed (like pandas), but for less common packages we have to install them first:
# https://pvlib-python.readthedocs.io/

%pip install pvlib --quiet
%pip install ochre-nrel

from dataclasses import dataclass
from enum import Enum
import calendar
import math
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pvlib
import pytz
from pathlib import Path
from typing import NamedTuple
import datetime
import json
import requests



# In this cell, we've pre-defined some helper functions you will use to fetch data from the EIA API
# You do not need to make changes to this cell

# There are three types of data we're fetching:
#  1. Generation by fuel type (Megawatt-hours): how much electricity is being generated by each fuel type
#  2. Demand (Megawatt-hours): how much electricity is being consumed
#  3. Interchange: how much electricity is being imported/exported from other balancing authorities

default_end_date = datetime.date.today().isoformat()
default_start_date = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()


def get_eia_timeseries(
    url_segment,
    facets,
    value_column_name="value",
    start_date=default_start_date,
    end_date=default_end_date,
    start_page=0,
    frequency="daily",
    include_timezone=True
):
    """
    A generalized helper function to fetch data from the EIA API
    """

    max_row_count = 5000  # This is the maximum allowed per API call from the EIA
    api_url = f"https://api.eia.gov/v2/electricity/rto/{url_segment}/data/?api_key={EIA_API_KEY}"
    offset = start_page * max_row_count

    if include_timezone and not "timezone" in facets:
        facets = dict(**{"timezone": ["Pacific"]}, **facets)

    response_content = requests.get(
        api_url,
        headers={
            "X-Params": json.dumps(
                {
                    "frequency": frequency,
                    "data": ["value"],
                    "facets": facets,
                    "start": start_date,
                    "end": end_date,
                    "sort": [{"column": "period", "direction": "desc"}],
                    "offset": offset,
                    "length": max_row_count,
                }
            )
        },
    ).json()
    print(response_content)

    # Sometimes EIA API responses are nested under a "response" key. Sometimes not 🤷
    if "response" in response_content:
        response_content = response_content["response"]

    print(f"{len(response_content['data'])} rows fetched")

    # Convert the data to a Pandas DataFrame and clean it up for plotting & analysis.
    dataframe = pd.DataFrame(response_content["data"])
    # Add a more useful timestamp column
    dataframe["timestamp"] = dataframe["period"].apply(
        pd.to_datetime, format="%Y/%m/%dT%H"
    )
    # Clean up the "value" column-
    # EIA always sends the value we asked for in a column called "value"
    # Oddly, this is sometimes sent as a string though it should always be a number.
    # We convert its dtype and set the name to a more useful one
    eia_value_column_name = "value"
    processed_df = dataframe.astype({eia_value_column_name: float}).rename(
        columns={eia_value_column_name: value_column_name}
    )

    # Pagination logic
    rows_fetched = len(processed_df) + offset
    rows_total = int(response_content["total"])
    more_rows_needed = rows_fetched != rows_total
    if more_rows_needed:
        # Recursive call to get remaining rows
        additional_rows = get_eia_timeseries(
            url_segment=url_segment,
            facets=facets,
            value_column_name=value_column_name,
            start_date=start_date,
            end_date=end_date,
            start_page=start_page + 1,
            frequency=frequency,
            include_timezone=include_timezone
        )
        return pd.concat([processed_df, additional_rows])
    else:
        return processed_df


def get_eia_grid_mix_timeseries(balancing_authorities, **kwargs):
    """
    Fetch electricity generation data by fuel type
    """
    return get_eia_timeseries(
        url_segment="daily-fuel-type-data",
        facets={"respondent": balancing_authorities},
        value_column_name="Generation (MWh)",
        **kwargs,
    )


def get_eia_net_demand_and_generation_timeseries(balancing_authorities, **kwargs):
    """
    Fetch electricity demand data
    """
    return get_eia_timeseries(
        url_segment="daily-region-data",
        facets={
            "respondent": balancing_authorities,
            "type": ["D", "NG", "TI"],  # Filter out the "Demand forecast" (DF) type
        },
        value_column_name="Demand (MWh)",
        **kwargs,
    )


def get_eia_interchange_timeseries(balancing_authorities, **kwargs):
    """
    Fetch electricity interchange data (imports & exports from other utilities)
    """
    return get_eia_timeseries(
        url_segment="daily-interchange-data",
        facets={"toba": balancing_authorities},
        value_column_name=f"Interchange to local BA (MWh)",
        **kwargs,
    )


# In this cell, we define a few permanent constants, as well as a HomeCharacteristics dataclass to help organize our inputs
# You do not need to make changes to this cell



# Also define a few permanent constants
JOULES_PER_KWH = 3.6e+6
JOULES_PER_MEGAJOULE = 1e6
SECONDS_PER_HOUR = 3600
AIR_VOLUMETRIC_HEAT_CAPACITY = 1200 # Energy in joules per cubic meter of air per degree K. (J/m3/K)

# To keep things tidier, we define a HomeCharacteristics dataclass to bunch all the defined and calculated attributes together
@dataclass
class HomeCharacteristics:
    latitude: float
    longitude: float
    heating_setpoint_c: int
    cooling_setpoint_c: int
    hvac_capacity_w: int
    hvac_overall_system_efficiency: int
    conditioned_floor_area_sq_m: int
    ceiling_height_m: int
    wall_insulation_r_value_imperial: int
    ach50: int
    south_facing_window_size_sq_m: int
    window_solar_heat_gain_coefficient: int
    can_close_curtains: bool
    smart_hvac_algorithm: bool

    @property
    def building_volume_cu_m(self) -> int:
        return self.conditioned_floor_area_sq_m * self.ceiling_height_m

    @property
    def building_perimeter_m(self) -> float:
        # Assume the building is a 1-story square
        return math.sqrt(self.conditioned_floor_area_sq_m) * 4
    
    @property
    def surface_area_to_area_sq_m(self) -> float:
        # Surface area exposed to air = wall area + roof area (~= floor area, for 1-story building)
        return self.building_perimeter_m * self.ceiling_height_m + self.conditioned_floor_area_sq_m

    @property
    def ach_natural(self) -> float:
        # "Natural" air changes per hour can be roughly estimated from ACH50 with an "LBL_FACTOR"
        # https://building-performance.org/bpa-journal/ach50-achnat/
        LBL_FACTOR = 17
        return self.ach50 / LBL_FACTOR

    @property
    def wall_insulation_r_value_si(self) -> float:
        # The R-values you typically see on products in the US will be in imperial units (ft^2 °F/Btu)
        # But our calculations need SI units (m^2 °K/W)
        return self.wall_insulation_r_value_imperial / 5.67 # SI units: m^2 °K/W

    @property
    def building_heat_capacity(self) -> int:
        # Building heat capacity
        # How much energy (in kJ) do you have to put into the building to change the indoor temperature by 1 degree?
        # Heat capacity unit: Joules per Kelvin degree (kJ/K)
        # A proper treatment of these factors would include multiple thermal mass components,
        # because the walls, air, furniture, foundation, etc. all store heat differently.
        # More info: https://www.greenspec.co.uk/building-design/thermal-mass/
        HEAT_CAPACITY_FUDGE_FACTOR = 1e5
        return self.building_volume_cu_m * HEAT_CAPACITY_FUDGE_FACTOR






    def get_carbon_intensity(start_date, end_date, ba_name):
    # Carbon intensity for each hour of the year in the given balancing authority
    # (so far not accounting for the effect of importing energy from neighboring grids)

    hourly_mix = get_eia_timeseries(
        url_segment="fuel-type-data",
        facets={"respondent": [ba_name]},
        value_column_name="Generation (MWh)",
        frequency="local-hourly",
        start_date = start_date.isoformat(),
        end_date = end_date.isoformat(),
        include_timezone=False)
    # We would like timezone, but the EIA API rejects our request if we set timezone=true.
    # We'll just have to assume that the EIA timeseries is in the same timezone as our
    # modeled building

    # TODO apply the import/export logic to this as well

    # From https://www.eia.gov/tools/faqs/faq.php?id=74&t=11
    # estimates of CO2e per kwh for fossil fuels:
    emissions = {
        "COL": 2.30,
        "NG": 0.97,
        "OIL": 2.38,
        "NUC": 0,
        "SUN": 0,
        "WAT": 0,
        "WND": 0,
        "OTH": 0.86, # from EIA's "average across all power sources", shrug emoji
    }


    hourly_mix["emissions_per_kwh"] = hourly_mix["fueltype"].apply(lambda x: emissions[x])
    hourly_mix["emissions"] = hourly_mix["emissions_per_kwh"] * hourly_mix["Generation (MWh)"] * 1000

    intensity_by_hour = hourly_mix[["Generation (MWh)", "emissions", "timestamp"]].groupby(
        ["timestamp"]).aggregate("sum").reset_index()

    intensity_by_hour["pounds_co2_per_kwh"] = intensity_by_hour["emissions"] / (intensity_by_hour["Generation (MWh)"]*1000)

    # the following lines are for a visualization we're not doing - TODO move this out
    #intensity_by_hour["hour"] = intensity_by_hour.timestamp.apply(lambda x: x.hour)
    # Note we get different results here depending on whether we treat this avg as "all hours weighted equally" (current behavior)
    # vs "all kwh weighted equally" (big kwh days matter more)
    #avg_intensity_by_hour = intensity_by_hour[["hour", "pounds_co2_per_kwh"]].groupby(["hour"]).aggregate("mean").reset_index()

    return intensity_by_hour





#building_latitude, building_longitude = 37.566504300139655, -122.37997055249495
# Nueva school

# jeffersonville vermont lat/lon: 44.64536116761554, -72.82704009279546
building_latitude, building_longitude = 44.64536116761554, -72.82704009279546



# In this cell, we set various home and HVAC system attributes
# You'll make changes to this cell! Tweak some of the input values to better match your own home's characteristics

old_home = HomeCharacteristics(
    ## Location
    # Change the two lines below to your home's latitude and longitude. (Find on Google Maps: https://support.google.com/maps/answer/18539)
    latitude = building_latitude, #36.1248871, # Las Vegas, NV
    longitude = building_longitude, #-115.3398063, # Las Vegas, NV

    ## HVAC temperature setpoints (i.e. your thermostat settings)
    # Your HVAC system will start heating your home if the indoor temperature is below HEATING_SETPOINT_C (house is too cold)
    # It will start cooling your home if the indoor temperature is above COOLING_SETPOINT_C (house is too warm)
    # Change the two lines below to match your thermostat settings
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

# https://www.energystar.gov/saveathome/seal_insulate/methodology
#https://www.energystar.gov/saveathome/seal_insulate/identify-problems-you-want-fix/diy-checks-inspections/insulation-r-values
# Energy Star uses R11 as baseline value for unimproved home. R60 is the highest they list
# (recommended for attics in Alaska!) so i'm using that as upper range of feasible.


smart_home = HomeCharacteristics(
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



def get_historical_solar_weather(simulation_year, latitude, longitude):
    # Use pvlib to fetch historical "solar weather" data for our chosen location for a specific year in the past
    # "Solar weather" is how much sun we got at this location

    # We're going to simulate our home's electricity usage over a year, using historical weather data for an
    # actual year in the past

    solar_weather_timeseries, solar_weather_metadata = pvlib.iotools.get_psm3(
        latitude=latitude,
        longitude=longitude,
        names=SIMULATION_YEAR,
        api_key=NREL_API_KEY,
        email=NREL_API_EMAIL,
        map_variables=True,
        leap_day=True,
    )

    solar_position_timeseries = pvlib.solarposition.get_solarposition(
        time=solar_weather_timeseries.index,
        latitude=old_home.latitude,
        longitude=old_home.longitude,
        altitude=100, # Assume close to sea level, this doesn't matter much
        temperature=solar_weather_timeseries["temp_air"],
    )

    window_irradiance = pvlib.irradiance.get_total_irradiance(
        90, # Window tilt (90 = vertical)
        180, # Window compass orientation (180 = south-facing)
        solar_position_timeseries.apparent_zenith,
        solar_position_timeseries.azimuth,
        solar_weather_timeseries.dni,
        solar_weather_timeseries.ghi,
        solar_weather_timeseries.dhi,
    )

    return solar_weather_timeseries, window_irradiance




def basic_hvac_algorithm(timestamp, indoor_temperature_c, outdoor_temperature_c, home, dt):
    # HVAC systems are either "on" or "off", so the energy they add or remove at any one time equals their total capacity


    if indoor_temperature_c < home.heating_setpoint_c:
        hvac_mode = "heating"
        energy_from_hvac_j = home.hvac_capacity_w * dt.seconds
    elif indoor_temperature_c > home.cooling_setpoint_c:
        hvac_mode = "cooling"
        energy_from_hvac_j = -home.hvac_capacity_w * dt.seconds
        # TODO: allow heating efficiency and cooling efficiency to be different.
    else:
        hvac_mode = "off"
        energy_from_hvac_j = 0

    return (hvac_mode, energy_from_hvac_j)

def smart_hvac_algorithm(timestamp, indoor_temperature_c, outdoor_temperature_c, home, dt):
    # TODO: if we have a smart thermostat, let's use a different algorithm here:
    # Divide hours into cheap, average, and expensive.
    # During average hours, keep temperature within narrow range as in basic algorithm above.
    # During expensive hours, use a wider range (allow less comfortable temperature).
    # During cheap hours, if an expensive hour is coming up soon (how soon?) then move the
    # temperature as far as possible (within the wider range) in the direction of where we want it to be later.
    # Basically banking up extra heat if heating will be more expensive later, banking up cold if cooling will be
    # more expensive later.
    return (hvac_mode, energy_from_hvac_j)


# In this cell, we put it all together and simulate the electricity usage of our HVAC system, given a year of historical weather
# You do not need to make changes to this cell

# We're modeling the effect of three external sources of energy that can affect the temperature of the home: 
#  1. Conductive heat gain or loss through contact with the walls and roof (we ignore the floor), given outdoor temperature
#  2. Air change heat gain or loss through air changes between air in the house and outside, given outdoor temperature
#  3. Radiant heat gain from sun coming in south-facing windows

# We then model our HVAC system as heating/cooling/off depending on whether the temperature is above or below desired setpoints

def calculate_next_timestep(
    timestamp,
    indoor_temperature_c,
    outdoor_temperature_c,
    irradiance,
    home: HomeCharacteristics,
    dt=pd.Timedelta(minutes=10) # Defaulting to a timestep of 10 minute increments
):
    '''
    This function calculates the ΔT (the change in indoor temperature) during a single timestep given:
      1. Previous indoor temperature
      2. Current outdoor temperature (from historical weather data)
      3. Current solar irradiance through south-facing windows (from historical weather data)
      4. Home and HVAC characteristics
    '''

    temperature_difference_c = outdoor_temperature_c - indoor_temperature_c

    # Calculate energy in to building

    # 1. Energy conducted through walls & roof (in Joules, J)
    # Conduction
    # Q = U.A.dT, where U = 1/R
    # Convection:
    # Q = m_dot . Cp * dT <=> Q = V_dot * Cv * dT (Cv = Rho * Cp)

    power_in_through_surface_w = (
        temperature_difference_c * home.surface_area_to_area_sq_m / home.wall_insulation_r_value_si
    )
    energy_from_conduction_j = power_in_through_surface_w * dt.seconds

    # 2. Energy exchanged through air changes with the outside air (in Joules, J)
    air_change_volume = (
        dt.seconds * home.building_volume_cu_m * home.ach_natural / SECONDS_PER_HOUR
    )
    energy_from_air_change_j = (
        temperature_difference_c * air_change_volume * AIR_VOLUMETRIC_HEAT_CAPACITY
    )

    # 3. Energy radiating from the sun in through south-facing windows (in Joules, J)
    energy_from_sun_j = (
        home.south_facing_window_size_sq_m
        * home.window_solar_heat_gain_coefficient
        * irradiance
        * dt.seconds
    )
    if indoor_temperature_c > home.cooling_setpoint_c and home.can_close_curtains:
        # Assume we close the curtains whenever we don't want heating, and this cuts
        # radiant energy by 90% (a figure i just made up)
        energy_from_sun_j *= 0.1

    # 4. Energy added or removed by the HVAC system (in Joules, J)
    if home.smart_hvac_algorithm:
        hvac_mode, energy_from_hvac_j = smart_hvac_algorithm(
            timestamp, indoor_temperature_c, outdoor_temperature_c, home, dt)
    else:
        hvac_mode, energy_from_hvac_j = basic_hvac_algorithm(
            timestamp, indoor_temperature_c, outdoor_temperature_c, home, dt)

    total_energy_in_j = (
        energy_from_conduction_j
        + energy_from_air_change_j
        + energy_from_sun_j
        + energy_from_hvac_j
    )

    # ΔT is the change in indoor temperature during this timestep resulting from the total energy input
    delta_t = total_energy_in_j / home.building_heat_capacity

    return pd.Series(
        {
            "timestamp": timestamp,
            "temperature_difference_c": temperature_difference_c,
            "Conductive energy (J)": energy_from_conduction_j,
            "Air change energy (J)": energy_from_air_change_j,
            "Radiant energy (J)": energy_from_sun_j,
            "HVAC energy (J)": energy_from_hvac_j,
            "hvac_mode": hvac_mode,
            "Net energy xfer": total_energy_in_j,
            "ΔT": delta_t,
            "Outdoor Temperature (C)": outdoor_temperature_c,
            "Indoor Temperature (C)": indoor_temperature_c + delta_t,
            # Actual energy consumption from the HVAC system:
            "HVAC energy use (kWh)": abs(energy_from_hvac_j) / (JOULES_PER_KWH * home.hvac_overall_system_efficiency)
        }
    )





def model_one_house(home, solar_weather_timeseries, window_irradiance, carbon_intensity):
    # Since we're starting in January, let's assume our starting temperature is the heating setpoint
    previous_indoor_temperature_c = home.heating_setpoint_c

    timesteps = []
    for timestamp in solar_weather_timeseries.index:
        new_timestep = calculate_next_timestep(
            timestamp=timestamp,
            indoor_temperature_c=previous_indoor_temperature_c,
            outdoor_temperature_c=solar_weather_timeseries.loc[timestamp].temp_air,
            irradiance=window_irradiance.loc[timestamp].poa_direct,
            home=home,
        )
        timesteps.append(new_timestep)
        previous_indoor_temperature_c = new_timestep["Indoor Temperature (C)"]

    # Estimate CO2 intensity of energy spent on HVAC depending on time of day.

    house_simulation = pd.DataFrame(timesteps)
    
    # check that our carbon_intensity has the same number of rows (should be one per hour)
    # as the timesteps:
    #print("carbon intensity goes from {} to {} ".format(carbon_intensity.timestamp.min(), carbon_intensity.timestamp.max()))
    #print("simulation goes from {} to {}".format(dataframe.timestamp.min(), dataframe.timestamp.max()))
    #if len(carbon_intensity) != len(dataframe):
    #    raise Exception("Given {} rows of carbon intensity for {} rows of simulation".format(len(carbon_intensity), len(dataframe)))
    # Should I raise an exception if start dates don't match or end dates don't match?
    # I think i'm currently off by like one hour - possibly due to time zones?


    # Merge using hourly, non-timezoned timestamps (Assume both are in local time and
    # that the EIA grid data is in the same timezone as the solar data. TODO: raise an exception
    # if they are not in the same timezone.)
    carbon_intensity["timestamp_hour_no_tz"] = carbon_intensity_2022.timestamp.apply(
        lambda x: x.replace(tzinfo=None))
    house_simulation["timestamp_hour_no_tz"] = house_simulation.timestamp.apply(
        lambda x: datetime.datetime(year=x.year, month=x.month,
                                    day=x.day, hour=x.hour)
    )

    house_simulation = house_simulation.merge(carbon_intensity, how="left", on="timestamp_hour_no_tz")

    house_simulation["pounds_co2"] = house_simulation["HVAC energy use (kWh)"] * house_simulation["pounds_co2_per_kwh"]
    
    house_simulation.drop(columns=["timestamp_x", "timestamp_y"], inplace=True)
    house_simulation.rename(columns={"timestamp_hour_no_tz": "timestamp"}, inplace=True)
    return house_simulation






def monthly_energy_balance( baby_energy_model):
    # For each month, let's look at the overall energy balance:
    # Where is the thermal energy in the house coming from, and where is it going to?
    energy_transfer_columns = [col for col in baby_energy_model.columns if col.endswith("(J)")]
    get_month=lambda idx: baby_energy_model.loc[idx]['timestamp'].month
    monthly_energy_balance_mj = baby_energy_model.groupby(by=get_month)[energy_transfer_columns].sum() / JOULES_PER_MEGAJOULE

    monthly_energy_balance_mj['month'] = monthly_energy_balance_mj.index.map(lambda month_idx: f'{month_idx:0=2} - {calendar.month_name[month_idx]}')

    monthly_energy_balance_tidy = monthly_energy_balance_mj.melt(id_vars='month')
    return monthly_energy_balance_tidy


ba_name = "CISO" # TODO - look this up from building's lat-lon
start_date = datetime.date(year=2022, month=1, day=1)
end_date = datetime.date(year=2023, month=1, day=1)
carbon_intensity_2022 = get_carbon_intensity(start_date, end_date, ba_name)
carbon_intensity_2022.columns

# 2022 is the most recent year for which we can get historical solar weather data from NREL (but you could choose an earlier year)
SIMULATION_YEAR = 2022 

historical_weather_2022, window_irradiance_2022 = get_historical_solar_weather(
    SIMULATION_YEAR, old_home.latitude, old_home.longitude)




#carbon_intensity_2022.timestamp.dtype
#historical_weather_2022.index.dtype

# Wait why is historical weather on half-hour offsets? thats' gonna complicate my attempt to do a join.
# Historical weather is coming back with a timezone of -5. That's US eastern time right?
# (Complicated by daylight savings)
# Weather time series starts at half-past midnight on Jan 1. so maybe it's just putting the observation
# for that hour at the center of the hour.

# Meanwhile, carbon intensity has a -8 on it (us pacific time)
# These both seem correct!!
# Maybe print a warning if they're not the same time zone, then drop time zones, then offset by 30 mins,
# then merge?
#historical_weather_2022.index.tz
# Timezone is a property of the index rather than any of the row values.
# carbon_intensity_2022["timestamp.values[0].tz

#carbon_intensity_2022.timestamp
# Wait why do my carbon intensity timestamps start at 9am instead of midnight jan 1?
# The ISOformat dates that I send to the API are just like '2022-01-01', no time info, so this must be
# a quirk of the EIA API.
#datetime.date(year=2022, month=1, day=1).isoformat()

#carbon_intensity_2022["timestamp_hour_no_tz"] = carbon_intensity_2022.timestamp.apply(
#    lambda x: x.replace(tzinfo=None))
#historical_weather_2022["timestamp_hour_no_tz"] = historical_weather_2022.apply(
#    lambda row: datetime.datetime(year=int(row["Year"]), month=int(row["Month"]),
#                                  day=int(row["Day"]), hour=int(row["Hour"])),
#    axis=1
#)
#
#historical_weather_2022.merge(carbon_intensity_2022, how="left", on="timestamp_hour_no_tz")




# assume old home and new home got exactly the same weather and used same electricity sources:
old_home_model = model_one_house(old_home, historical_weather_2022, window_irradiance_2022, carbon_intensity_2022)
smart_home_model = model_one_house(smart_home, historical_weather_2022, window_irradiance_2022, carbon_intensity_2022)
old_monthly_balance = monthly_energy_balance(old_home_model)
smart_monthly_balance = monthly_energy_balance(smart_home_model)




yearly_total_old_home = old_home_model['pounds_co2'].sum()
yearly_total_smart_home = smart_home_model['pounds_co2'].sum()
print("Old home total: {} vs smart home total: {} - difference of {}".format(
    yearly_total_old_home,
    yearly_total_smart_home,
    yearly_total_old_home - yearly_total_smart_home
))



# Coding Level 2-3 - Carry on!

# If you have strong programming experience, use this as a starting point and modify or expand this notebook. Some ideas:
#  - The biggest weakness in this model is how thermal mass is mostly ignored. Integrate a more realistic thermal mass component.
#  - We didn't get hands-on with OpenStudio/EnergyPlus/Resstock because of the difficulty of introducing all the dependencies (they're in Java+Ruby).
#       However, NREL has a bleeding-edge, all-python residential energy modeling project: https://github.com/NREL/OCHRE
#       Install their project (%pip install ochre-nrel), fire it up, and compare it to the toy model.
#  - Calculate your estimated electricy costs (due to HVAC electricity usage)
#    (US average electricity price is around $USD 0.23 per kilowatt-hour, but this can vary widely by location)
#  - Fetch TMY data (Typical Meterological Year, averaged across several years) instead of a data from a specific year
#  - Iterate over one or more attributes (programmatically, with charts to compare the outputs)
#  - Look up your actual electricity usage & compare to these simulated results (you might expect HVAC to be around 30-50% of total usage)
#  - Improve this model - account for more factors!
#  - Combine this notebook with the rooftop solar notebook to model what capacity PV system you would need to operate off-grid, 
#    i.e. meet your energy usage for each hour of the year, not just in total (accounting for high usage but low generation in winter)

# https://github.com/NREL/OCHRE

#import datetime as dt
#from ochre import Dwelling


#dwelling_args = {
#    # 'name': 'OCHRE_Test_House'  # simulation name#
#
#    # Timing parameters
#    'start_time': dt.datetime(2018, 1, 1, 0, 0),  # year, month, day, hour, minute
#    'time_res': dt.timedelta(minutes=10),         # time resolution of the simulation
#    'duration': dt.timedelta(days=3),             # duration of the simulation
#    'initialization_time': dt.timedelta(days=1),  # used to create realistic starting temperature
#    'time_zone': None,                            # option to specify daylight savings, in development#
#
#    # Input parameters - Sample building (uses HPXML file and time series schedule file)
#    'hpxml_file': os.path.join(default_input_path, 'Input Files', 'sample_resstock_properties.xml'),
#    'schedule_input_file': os.path.join(default_input_path, 'Input Files', 'sample_resstock_schedule.csv'),
#
#    # Input parameters - weather (note weather_path can be used when Weather Station is specified in HPXML file)
#    # 'weather_path': weather_path,
#    'weather_file': os.path.join(default_input_path, 'Weather', 'USA_CO_Denver.Intl.AP.725650_TMY3.epw'),
#
#    # Output parameters
#    'verbosity': 6,                         # verbosity of time series files (0-9)


#house = Dwelling(simulation_name, 
#                 start_time=dt.datetime(2018, 1, 1, 0, 0),
#                 time_res=dt.timedelta(minutes=10),       
#                 duration=dt.timedelta(days=3),
#                 properties_file='sample_resstock_house.xml',
#                 schedule_file='sample_resstock_schedule.csv',
#                 weather_file='USA_CO_Denver.Intl.AP.725650_TMY3.epw',
#                 verbosity=3,
#                 )
# outputs: 
#   df: a Pandas DataFrame with 10 minute resolution
#    metrics: a dictionary of energy metrics
#    hourly: a Pandas DataFrame with 1 hour resolution (verbosity >= 3 only)

#df, metrics, hourly = dwelling.simulate()