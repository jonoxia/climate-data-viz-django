import datetime
import json
import os
import requests
import pandas as pd
from django.conf import settings
from io import StringIO
from .models import EIAHourlyDataCache

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
    if cache_hits.count() == 1:
        virtual_file = StringIO()
        virtual_file.write(cache_hits[0].response_csv)
        virtual_file.seek(0)
        cached_df = pd.read_csv( virtual_file )
        virtual_file.close()
        return cached_df

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
    print("Got result df with {} rows".format(len(result_df)))

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
    Fetch electricity generation data by fuel type
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="daily-fuel-type-data",
        facets={"respondent": balancing_authorities},
        value_column_name="Generation (MWh)",
        **kwargs,
    )

def get_hourly_eia_grid_mix(balancing_authorities, **kwargs):
    """
    Fetch elecgtricity generation data by fuel type, but hourly
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="fuel-type-data",
        facets={"respondent": [balancing_authorities]},
        value_column_name="Generation (MWh)",
        frequency="local-hourly",
        include_timezone=False,
        **kwargs,
    )


def get_daily_eia_net_demand_and_generation_timeseries(balancing_authorities, **kwargs):
    """
    Fetch electricity demand data
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
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="region-data",
        facets={"respondent": [balancing_authorities],
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
    """
    return cache_wrapped_get_eia_timeseries(
        url_segment="interchange-data",
        facets={"toba": [LOCAL_BALANCING_AUTHORITY],
        },
        value_column_name=f"Interchange to local BA (MWh)",
        frequency="local-hourly",
        include_timezone=False,
        **kwargs
    )

