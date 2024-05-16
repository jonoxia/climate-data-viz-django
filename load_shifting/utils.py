import datetime
import json
import os
import requests
import pandas as pd
from django.conf import settings
from io import StringIO
from .models import EIAHourlyDataCache, HourlyGenerationMixCache

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
    "Other": 0.86,
}

default_end_date = datetime.date.today()
default_start_date = (datetime.date.today() - datetime.timedelta(days=365))



def cache_wrapped_get_eia_timeseries(url_segment,
    facets,
    value_column_name="value",
    start_date=default_start_date,
    end_date=default_end_date,
    frequency="daily",
    include_timezone=True
):
    # Check cache:
    print("Checking cache - {}".format(json.dumps(facets)))
    cache_hits = EIAHourlyDataCache.objects.filter(
        url_segment = url_segment,
        start_date = start_date,
        end_date = end_date,
        facets = json.dumps(facets))
    if cache_hits.count() > 0:
        print("Hit Cache")
        virtual_file = StringIO()
        virtual_file.write(cache_hits[0].response_csv)
        virtual_file.seek(0)
        cached_df = pd.read_csv( virtual_file )
        virtual_file.close()
        return cached_df

    print("Missed Cache")
    import pdb; pdb.set_trace()
    result_df = get_eia_timeseries_recursive(
        url_segment,
        facets,
        value_column_name=value_column_name,
        start_date=start_date,
        end_date=end_date,
        start_page=0,
        frequency=frequency,
        include_timezone=include_timezone
    )

    # Write to cache:
    virtual_file = StringIO()
    result_df.to_csv(virtual_file)
    virtual_file.seek(0)
    print("Cacheing for facets {}".format(json.dumps(facets)))
    new_cache = EIAHourlyDataCache.objects.create(
        url_segment = url_segment,
        start_date = start_date,
        end_date = end_date,
        facets = json.dumps(facets),
        response_csv = virtual_file.read(),
        cached_date = datetime.datetime.now()
    )
    virtual_file.close()
    new_cache.save()

    return result_df



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
        raise( Exeption("no data rows"))

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


def cache_wrapped_hourly_gen_mix_by_ba_and_type(ba, start_date, end_date):
    # Check for cache hits:

    # TODO probably turn this cache-wrapping into a decorator
    print("Checking cache - {}".format(ba))
    cache_hits = HourlyGenerationMixCache.objects.filter(
        ba_name = ba,
        start_date = start_date,
        end_date = end_date)
    if cache_hits.count() > 0:
        print("Hit Cache")
        virtual_file = StringIO()
        virtual_file.write(cache_hits[0].calculated_csv)
        virtual_file.seek(0)
        cached_df = pd.read_csv( virtual_file )
        virtual_file.close()
        return cached_df

    consumption_by_ba = compute_hourly_consumption_by_source_ba(ba, start_date, end_date)
    usage_by_ba_and_type = compute_hourly_fuel_mix_after_import_export(ba, consumption_by_ba, start_date, end_date)

    # Write to cache:
    virtual_file = StringIO()
    usage_by_ba_and_type.to_csv(virtual_file)
    virtual_file.seek(0)
    print("Cacheing for ba {}".format(ba))
    new_cache = HourlyGenerationMixCache.objects.create(
        ba_name = ba,
        start_date = start_date,
        end_date = end_date,
        calculated_csv = virtual_file.read(),
        cached_date = datetime.datetime.now()
    )
    virtual_file.close()
    new_cache.save()

    return usage_by_ba_and_type
