import datetime
import json
import os
import requests
import pandas as pd
from django.conf import settings
from io import StringIO
from .models import AllPurposeCSVCache
from dataclasses import dataclass
import pvlib


# From https://www.eia.gov/tools/faqs/faq.php?id=74&t=11
# estimates of CO2e per kwh for fossil fuels:
EMISSIONS_BY_FUEL = {
    "COL": 2.30,
    "NG": 0.97,
    "OIL": 2.38,
    "NUC": 0,
    "SUN": 0,
    "WAT": 0,
    "WND": 0,
    "OTH": 0.86, # from EIA's "average across all power sources", shrug emoji
    "Hydro": 0,
    "Solar": 0,
    "Petroleum": 2.38,
    "Nuclear": 0,
    "Natural gas": 0.97,
    "Wind": 0,
    "Coal": 2.30,
    "Other": 0.86, # TODO: if i determine "Other" is mostly battery, then set this to 0 and clear cache
}

default_end_date = datetime.date.today()
default_start_date = (datetime.date.today() - datetime.timedelta(days=365))

class EIAAPIExeption( Exception ):
    pass

def cache_csv( wrapped_function ):
    """
    Decorator for all-purpose cacheing of any function that queries or generates a data frame.
    Usage:

        @cache_csv
        def my_function(*args, start_date=xxx, end_date=xxxx):
       
    Wrapped function MUST:
    - return a Pandas data frame
    - take 'start_date' and 'end_date' keyword arguments
    - use keyword arguments for any parameters that you want to use as cache keys

    The function name is used as part of the cache key, so old cache entries will be invalidated
    if the function name changes. So change the name if you are changing the semantics, and don't
    change the name if you're not!
    """

    def wrapper(*args, **kwargs):

        function_name = wrapped_function.__name__
        if not "start_date" in kwargs:
            raise Exception("No start_date param in function {} (params: {})".format(function_name, kwargs.keys()))
        
        start_date = kwargs["start_date"]
        end_date = kwargs["end_date"]
        key_params_json = {
            key: kwargs[key] for key in kwargs.keys() if not key in ["start_date", "end_date"]
        }

        cache_hits = AllPurposeCSVCache.objects.filter(
            cache_function_name = function_name,
            key_params_json = json.dumps(key_params_json),
            start_date = start_date,
            end_date = end_date)
        if cache_hits.count() > 0:
            # Case of cache hit:
            virtual_file = StringIO()
            virtual_file.write(cache_hits[0].raw_csv)
            virtual_file.seek(0)
            cached_df = pd.read_csv( virtual_file )
            virtual_file.close()
            return cached_df

        # Case of cache miss:
        result_df = wrapped_function(*args, **kwargs)

        # Write new cache:
        virtual_file = StringIO()
        result_df.to_csv(virtual_file)
        virtual_file.seek(0)
        new_cache = AllPurposeCSVCache.objects.create(
            cache_function_name = function_name,
            cached_date = datetime.datetime.now(),
            key_params_json = json.dumps(key_params_json),
            start_date = start_date,
            end_date = end_date,
            raw_csv = virtual_file.read()
        )
        virtual_file.close()
        new_cache.save()
        return result_df

    return wrapper


@cache_csv
def cache_wrapped_get_eia_timeseries(
    url_segment="",
    facets={},
    value_column_name="value",
    start_date=default_start_date,
    end_date=default_end_date,
    frequency="daily",
    include_timezone=True
):

    return get_eia_timeseries_recursive(
        url_segment,
        facets,
        value_column_name=value_column_name,
        start_date=start_date,
        end_date=end_date,
        start_page=0,
        frequency=frequency,
        include_timezone=include_timezone
    )



def get_eia_timeseries_recursive(
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

    EIA_API_KEY = os.getenv("EIA_API_KEY")
    if EIA_API_KEY is None:
        EIA_API_KEY = settings.EIA_API_KEY
    assert EIA_API_KEY is not None

    max_row_count = 5000  # This is the maximum allowed per API call from the EIA
    api_url = f"https://api.eia.gov/v2/electricity/rto/{url_segment}/data/?api_key={EIA_API_KEY}"
    offset = start_page * max_row_count

    if include_timezone and not "timezone" in facets:
        facets = dict(**{"timezone": ["Pacific"]}, **facets)

    date_format = "%Y-%m-%d"
    response = requests.get(
        api_url,
        headers={
            "X-Params": json.dumps(
                {
                    "frequency": frequency,
                    "data": ["value"],
                    "facets": facets,
                    "start": datetime.datetime.strftime(start_date, date_format),
                    "end": datetime.datetime.strftime(end_date, date_format),
                    "sort": [{"column": "period", "direction": "desc"}],
                    "offset": offset,
                    "length": max_row_count,
                }
            )
        },
    )
    if response.status_code != 200:
        raise( Exception("EIA API gave status code {} reason {}".format(response.status_code, response.reason)))
    response_content = response.json()
    print(response_content) 

    # Sometimes EIA API responses are nested under a "response" key. Sometimes not 🤷
    if "response" in response_content:
        response_content = response_content["response"]

    print(f"{len(response_content['data'])} rows fetched")
    if len(response_content["data"]) == 0:
        raise( EIAAPIExeption("no data rows"))

    # Convert the data to a Pandas DataFrame and clean it up for plotting & analysis.
    dataframe = pd.DataFrame(response_content["data"])
    # Add a more useful timestamp column
    dataframe["timestamp"] = dataframe["period"].apply( pd.to_datetime ) # this seems to work?
    #pd.to_datetime , format="%Y/%m/%dT%H"
    #)
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
        # TODO probably be better to unroll this recursion
        additional_rows = get_eia_timeseries_recursive(
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



def get_daily_eia_grid_mix_timeseries(balancing_authorities, **kwargs):
    """
    Fetch electricity generation data by fuel type.
    balancing_authorities is an array.
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="daily-fuel-type-data",
        facets={"respondent": balancing_authorities},
        value_column_name="Generation (MWh)",
        **kwargs,
    )

def get_hourly_eia_grid_mix(balancing_authorities, **kwargs):
    """
    Fetch elecgtricity generation data by fuel type, but hourly.
    balancing_authorities is an array.
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="fuel-type-data",
        facets={"respondent": balancing_authorities},
        value_column_name="Generation (MWh)",
        frequency="local-hourly",
        include_timezone=False,
        **kwargs,
    )


def get_daily_eia_net_demand_and_generation_timeseries(balancing_authorities, **kwargs):
    """
    Fetch electricity demand data
    balancing_authorities is an array.
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="daily-region-data",
        facets={
            "respondent": balancing_authorities,
            "type": ["D", "NG", "TI"],  # Filter out the "Demand forecast" (DF) type
        },
        value_column_name="Demand (MWh)",
        **kwargs,
    )

def get_hourly_eia_net_demand_and_generation(balancing_authorities, **kwargs):
    """
        Fetch electricity demand data but hourly
    balancing_authorities is an array.
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="region-data",
        facets={"respondent": balancing_authorities,
        "type": ["D", "NG", "TI"],
        },
        value_column_name="Demand (MWh)",
        frequency="local-hourly",
        include_timezone=False,
        **kwargs
    )


def get_daily_eia_interchange_timeseries(balancing_authorities, **kwargs):
    """
    Fetch electricity interchange data (imports & exports from other utilities)
    balancing_authorities is an array.
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="daily-interchange-data",
        facets={"toba": balancing_authorities},
        value_column_name=f"Interchange to local BA (MWh)",
        **kwargs,
    )

def get_hourly_eia_interchange(balancing_authorities, **kwargs):
    """
    Fetch electricity interchange data (imports & exports) but hourly
    balancing_authorities is an array.
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="interchange-data",
        facets={"toba": balancing_authorities,
        },
        value_column_name=f"Interchange to local BA (MWh)",
        frequency="local-hourly",
        include_timezone=False,
        **kwargs
    )



def compute_supply_demand_by_hour(balancing_authority):
    # Supply and demand by hour of day:
    demand_df = get_hourly_eia_net_demand_and_generation([balancing_authority])
    demand_df["hour"] = demand_df.timestamp.apply(lambda x: x.hour)
    demand_by_hour = demand_df[["hour", "Demand (MWh)", "type-name"]].groupby(["hour", "type-name"]).sum().reset_index()
    return demand_by_hour


def compute_hourly_consumption_by_source_ba(balancing_authority, start_date, end_date):
    """
    First, more terminology (https://www.eia.gov/electricity/gridmonitor/about)

    Demand (D): energy consumed locally
    Net generation (NG): energy generated locally
    Total interchange (TI): net energy exported (positive means net outflow, negative means net inflow)

    The balancing authority is responsible for balancing this equation:
    Total interchange = Net generation - Demand
    i.e. if local generation is larger than local demand, the BA is exporting electricity (positive total interchange)
         if local demand is larger than local generation, the BA is importing electricity (negative total interchange)


    There are two paths to consider:

    1. Local BA is a net exporter of energy
    In this case, all electricity consumed locally comes from electricity generated locally, so the grid mix simply matches the local generation
    This turns out to be a trivial sub-case of path #2

    2. Local BA is a net importer of energy
    When the local BA is net importing energy, that energy might come from multiple other BAs, each of which has their own grid mix
    Therefore, the grid mix of consumed electricity is a combination of local generation grid mix and imported generation grid mix

    To get a true representation of the grid mix of local energy, we need to combine these pieces of data:
     - Demand, Net generation, and Total interchange for our LOCAL_BALANCING_AUTHORITY
     - Interchange (quantitiy of imported energy) with each connected balancing authority
     - Grid mix of imported energy from each connected balancing authority


    In the code below, we fetch the hourly Demand (D), Net generation (NG), and Total interchange (TI) numbers for the LOCAL_BALANCING_AUTHORITY
    You should see three rows for each date, one row each for TI, D, and NG.
    You can spot check a given day to confirm that TI = NG - D
    """

    demand_df = get_hourly_eia_net_demand_and_generation([balancing_authority], start_date=start_date, end_date=end_date)
    interchange_df = get_hourly_eia_interchange([balancing_authority], start_date=start_date, end_date=end_date)


    # How much energy is both generated and consumed locally
    def get_energy_generated_and_consumed_locally(df):
        """
        If local demand is smaller than net (local) generation, that means:
            amount generated and used locally == Demand (net export)
        If local generation is smaller than local demand, that means:
            amount generated and used locally == Net generation (net import)
        Therefore, the amount generated and used locally is the minimum of these two
        """
        demand_stats = df.groupby("type-name")["Demand (MWh)"].sum()
        
        try:
            return min(demand_stats["Demand"], demand_stats["Net generation"])
        except KeyError:
            # Sometimes for a particular timestamp we're missing demand or net generation. Be conservative and set it to zero
            print(f'Warning - either Demand or Net generation is missing from this timestamp. Values found for "type-name": {list(demand_stats.index)}')
            return 0

    # TODO: the above seems to be printing out an awful lot of warnings. Is this a problem?
    # TODO maybe we drop these rows instead of printing a warning?
    energy_generated_and_used_locally = demand_df.groupby("timestamp").apply(
        get_energy_generated_and_consumed_locally
    )

    consumed_locally_column_name = "Power consumed locally (MWh)"

    # How much energy is imported and then used locally, grouped by the source BA (i.e. the BA which generated the energy)
    energy_imported_then_consumed_locally_by_source_ba = (
        interchange_df.groupby(["timestamp", "fromba"])[
            "Interchange to local BA (MWh)"
        ].sum()
        # We're only interested in data points where energy is coming *in* to the local BA, i.e. where net export is negative
        # Therefore, ignore positive net exports
        .apply(lambda interchange: max(interchange, 0))
    )

    # Combine these two together to get all energy used locally, grouped by the source BA (both local and connected)
    energy_consumed_locally_by_source_ba = pd.concat(
        [
            energy_imported_then_consumed_locally_by_source_ba.rename(
                consumed_locally_column_name
            ).reset_index("fromba"),
            pd.DataFrame(
                {
                    "fromba": balancing_authority,
                    consumed_locally_column_name: energy_generated_and_used_locally,
                }
            ),
        ]
    ).reset_index()
    energy_consumed_locally_by_source_ba['timestamp'] = pd.to_datetime( energy_consumed_locally_by_source_ba.timestamp )
    return energy_consumed_locally_by_source_ba




def compute_hourly_fuel_mix_after_import_export(balancing_authority, energy_consumed_locally_by_source_ba, start_date, end_date):
    """
    Now that we know how much (if any) energy is imported by our local BA, and from which source BAs,
    let's get a full breakdown of the grid mix (fuel types) for that imported energy.
    """

    # First, get a list of all source BAs: our local BA plus the ones we're importing from
    all_source_bas = energy_consumed_locally_by_source_ba["fromba"].unique().tolist()

    # Rather than taking start_date and end_date arguments, just use start and end date from given
    # energy-consumed-locally dataframe
    hourly_eia_grid_mix = get_hourly_eia_grid_mix(
        all_source_bas,
        start_date = start_date, # energy_consumed_locally_by_source_ba.timestamp.min(),
        end_date = end_date) #energy_consumed_locally_by_source_ba.timestamp.max() )

    # Then, fetch the fuel type breakdowns for each of those BAs
    generation_types_by_ba = hourly_eia_grid_mix.rename(
        {"respondent": "fromba", "type-name": "generation_type"}, axis="columns"
    )
    print(len(generation_types_by_ba))
    generation_types_by_ba["timestamp"] = pd.to_datetime( generation_types_by_ba["timestamp"] )

    """
    Okay, we've fetched all the data we need, now it's time to combine it all together!

    What follows is some heavy-lifting with the Pandas library to massage the data into the shape we want
    Pandas docs: https://pandas.pydata.org/docs/
    Pandas cheat sheet: https://pandas.pydata.org/Pandas_Cheat_Sheet.pdf

    The goal is to get a DataFrame of energy used at the local BA (in MWh), broken down by both
     * the BA that the energy came from, and 
     * the fuel type of that energy.
    So we'll end up with one row for each combination of source BA and fuel type.

    To get there, we need to combine the amount of imported energy from each source ba with grid mix for that source BA.
    The general formula is:
    Power consumed locally from a (BA, fuel type) combination = 
       total power consumed locally from this source BA * (fuel type as a % of source BA's generation)
    fuel type as a % of source BA's generation = 
      (total generation at source BA) / (total generation for this fuel type at this BA)
    """

    total_generation_by_source_ba = generation_types_by_ba.groupby(["timestamp", "fromba"])[
        "Generation (MWh)"
    ].sum()
    generation_types_by_ba["timestamp"] = pd.to_datetime( generation_types_by_ba["timestamp"] )
    generation_types_by_ba_with_totals = generation_types_by_ba.join(
        total_generation_by_source_ba,
        how="left",
        on=["timestamp", "fromba"],
        rsuffix=" Total",
    )
    generation_types_by_ba_with_totals["Generation (% of BA generation)"] = (
        generation_types_by_ba_with_totals["Generation (MWh)"]
        / generation_types_by_ba_with_totals["Generation (MWh) Total"]
    )
    generation_types_by_ba_with_totals["timestamp"] = pd.to_datetime( generation_types_by_ba_with_totals.timestamp)
    energy_consumed_locally_by_source_ba["timestamp"] = pd.to_datetime( energy_consumed_locally_by_source_ba["timestamp"] )
    generation_types_by_ba_with_totals_and_source_ba_breakdown = generation_types_by_ba_with_totals.merge(
        energy_consumed_locally_by_source_ba.rename(
            {"Power consumed locally (MWh)": "Power consumed locally from source BA (MWh)"},
            axis="columns",
        ),
        on=["timestamp", "fromba"],
    )
    full_df_reindexed = (
        generation_types_by_ba_with_totals_and_source_ba_breakdown.set_index(
            ["timestamp", "fromba", "generation_type"]
        )
    )
    usage_by_ba_and_generation_type = (
        (
            full_df_reindexed["Power consumed locally from source BA (MWh)"]
            * full_df_reindexed["Generation (% of BA generation)"]
        )
        .rename("Usage (MWh)")
        .reset_index()
    )

    usage_by_ba_and_generation_type["emissions_per_kwh"] = usage_by_ba_and_generation_type["generation_type"].apply(lambda x: EMISSIONS_BY_FUEL[x])
    usage_by_ba_and_generation_type["emissions"] = usage_by_ba_and_generation_type["emissions_per_kwh"] * usage_by_ba_and_generation_type["Usage (MWh)"] * 1000

    return usage_by_ba_and_generation_type



@cache_csv
def cache_wrapped_hourly_gen_mix_by_ba_and_type(ba_name=None, start_date=None, end_date=None):
    consumption_by_ba = compute_hourly_consumption_by_source_ba(ba_name, start_date, end_date)
    usage_by_ba_and_type = compute_hourly_fuel_mix_after_import_export(ba_name, consumption_by_ba, start_date, end_date)
    return usage_by_ba_and_type


@cache_csv
def cache_wrapped_co2_boxplot_all_bas(ba_names = [], start_date=None, end_date=None):
    # A good way to visualize this might be: bar chart with floating bars, bottom end of each bar
    # is minimum co2 intensity, top end of each bar is maximum co2 intensity, show for each BA
    # one year ago and each BA today.
    # BAs with a big difference between max and min (likely if there's a lot of solar and not
    # a lot of batteries) are good targets for load-shifting.
    # candlestick chart? https://observablehq.com/@d3/candlestick-chart

    # for each BA, will have max, min, 0.25th percentile, median, 0.75th percentile.
    ba_stats = { "min": [], "max": [], "25%": [], "50%": [], "75%": []}
    good_ba_names = []
    
    # loop through for each ba, get min and max pounds_co2_per_kwh
    for ba_name in ba_names:
        if ba_name in ['NSB', 'OVEC', 'EEI', 'GLHB', 'AEC', 'GRIF', ]:
            # these return 0 rows for whatever reason
            continue
        try:
            usage_df = cache_wrapped_hourly_gen_mix_by_ba_and_type(
                ba_name=ba_name,
                start_date=start_date,
                end_date=end_date)
        except EIAAPIExeption as e:
            print("Couldn't get EIA data for {}".format(ba_name))
            continue

        # TODO: next two lines are copied from co2_intensity_json - factor these out!
        intensity_by_hour = usage_df[["Usage (MWh)", "emissions", "timestamp"]].groupby(
            ["timestamp"]).aggregate("sum").reset_index()

        intensity_by_hour["pounds_co2_per_kwh"] = intensity_by_hour["emissions"] / (intensity_by_hour["Usage (MWh)"]*1000)

        statistics = intensity_by_hour["pounds_co2_per_kwh"].describe()
        for key in ba_stats.keys():
            ba_stats[key].append(statistics[key])
        good_ba_names.append(ba_name)

    ba_stats["ba_names"] = good_ba_names
    return pd.DataFrame(data=ba_stats)


def cache_and_write_to_files():
    # Used to save caches to files for use in unit tests
    start_date = datetime.datetime(year=2024, month=4, day=1)
    end_date = datetime.datetime(year=2024, month=4, day=30)

    consumption_by_ba = compute_hourly_consumption_by_source_ba("CISO", start_date, end_date)
    #self.assertEqual(set(consumption_by_ba.columns), set(["timestamp", "fromba", "Power consumed locally (MWh)"]))
    usage_by_ba_and_type = compute_hourly_fuel_mix_after_import_export("CISO", consumption_by_ba, start_date, end_date)
    #usage_by_ba_and_type.head()

    for cache_object in EIAHourlyDataCache.objects.all():
        facets = json.loads(cache_object.facets)
        if "respondent" in facets:
            num_respondents = len(facets["respondent"])
        else:
            num_respondents = 0
        filename = "{}_{}_respondents.csv".format(
            cache_object.url_segment, num_respondents)

        with open(filename, "w") as outfile:
            outfile.write(cache_object.response_csv)

@cache_csv
def get_historical_solar_weather(start_date = None, end_date = None, latitude=0, longitude=0):
    # Use pvlib to fetch historical "solar weather" data for our chosen location for a specific year in the past
    # "Solar weather" is how much sun we got at this location

    NREL_API_KEY = os.getenv("NREL_API_KEY") # don't see this in hex notebook (??)
    if NREL_API_KEY is None:
        NREL_API_KEY = settings.NREL_API_KEY
    assert NREL_API_KEY is not None

    NREL_API_EMAIL = os.getenv("NREL_API_EMAIL") # don't see this in hex notebook (??)
    if NREL_API_EMAIL is None:
        NREL_API_EMAIL = settings.NREL_API_EMAIL
    assert NREL_API_EMAIL is not None

    simulation_year = end_date.year # !

    solar_weather_timeseries, solar_weather_metadata = pvlib.iotools.get_psm3(
        latitude=latitude,
        longitude=longitude,
        names=simulation_year,
        api_key=NREL_API_KEY,
        email=NREL_API_EMAIL,
        map_variables=True,
        leap_day=True,
    )

    return solar_weather_timeseries
            

@cache_csv
def get_historical_window_irradiance(start_date = None, end_date = None, latitude=0, longitude=0):

    solar_weather_timeseries = get_historical_solar_weather(**kwargs)
    
    solar_position_timeseries = pvlib.solarposition.get_solarposition(
        time=solar_weather_timeseries.index,
        latitude=latitude,
        longitude=longitude,
        altitude=100, # Assume close to sea level, this doesn't matter much
        temperature=solar_weather_timeseries["temp_air"],
    )

    window_irradiance = pvlibo.irradiance.get_total_irradiance(
        90, # Window tilt (90 = vertical)
        180, # Window compass orientation (180 = south-facing)
        solar_position_timeseries.apparent_zenith,
        solar_position_timeseries.azimuth,
        solar_weather_timeseries.dni,
        solar_weather_timeseries.ghi,
        solar_weather_timeseries.dhi,
    )

    return window_irradiance


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
