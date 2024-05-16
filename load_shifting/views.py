from django.shortcuts import render
from django.http import JsonResponse
import pandas as pd
from .utils import get_hourly_eia_net_demand_and_generation, get_hourly_eia_interchange, get_hourly_eia_grid_mix
from .utils import compute_hourly_consumption_by_source_ba, compute_hourly_fuel_mix_after_import_export
import datetime
import json
from .models import EIAHourlyDataCache

def populate_db_cache():
    pass

def retrieve_db_cache():
    pass



def cache_and_write_to_files():
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



def index(request):
    context = {}

    cache_and_write_to_files()

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
