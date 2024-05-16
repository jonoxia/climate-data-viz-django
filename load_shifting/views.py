from django.shortcuts import render
from django.http import JsonResponse
import pandas as pd
from .utils import get_hourly_eia_net_demand_and_generation, get_hourly_eia_interchange, get_hourly_eia_grid_mix
from .utils import compute_hourly_consumption_by_source_ba, compute_hourly_fuel_mix_after_import_export, cache_wrapped_hourly_gen_mix_by_ba_and_type
import datetime
import json



def index(request):
    context = {}
    return render(request, "load_shifting/pie.html", context)


def energy_mix_json(request):
    # TODO get these 3 from the request:
    ba = "CISO"
    start_date = datetime.datetime(year=2024, month=4, day=1)
    end_date = datetime.datetime(year=2024, month=4, day=30)

    hourly_usage = get_hourly_eia_grid_mix([ba], start_date = start_date, end_date = end_date)
    hourly_usage["hour"] = pd.to_datetime(hourly_usage.period, format="ISO8601").apply(lambda x: x.hour)
    print(hourly_usage["type-name"].unique())

    # Cache this data frame into HourlyGenerationMixCache!!!

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

    
    usage_df = cache_wrapped_hourly_gen_mix_by_ba_and_type(ba, start_date, end_date)
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
    return JsonResponse({"time_series": json_data_series})

    # A good way to visualize this might be: bar chart with floating bars, bottom end of each bar
    # is minimum co2 intensity, top end of each bar is maximum co2 intensity, show for each BA
    # one year ago and each BA today.
    # BAs with a big difference between max and min (likely if there's a lot of solar and not
    # a lot of batteries) are good targets for load-shifting.
    # candlestick chart? https://observablehq.com/@d3/candlestick-chart
