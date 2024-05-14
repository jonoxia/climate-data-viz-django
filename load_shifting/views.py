from django.shortcuts import render
from django.http import JsonResponse
import pandas as pd
from .utils import get_hourly_eia_net_demand_and_generation, get_hourly_eia_interchange, get_hourly_eia_grid_mix



def populate_db_cache():
    pass

def retrieve_db_cache():
    pass



def index(request):
    context = {}
    return render(request, "load_shifting/pie.html", context)


def energy_mix_json(request):
    # Replace this with a query to the db cache
    df = pd.DataFrame(data = {
        "hour": [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
        "fuel": ["Solar", "Wind", "Hydro", "Nuclear", "Natural Gas","Solar", "Wind", "Hydro", "Nuclear", "Natural Gas"],
        "mwh": [53245, 28479, 19697, 24037, 40245, 13245, 18479, 19697, 24037, 80245]
    })

    # Convert data frame to the JSON format expected by D3.js:
    json_data_series = []
    for hour in df["hour"].unique():
        sub_frame = df[ df["hour"] == hour ]
        json_data_series.append(
            {"key": "Hour = {}".format(hour),
             "values": sub_frame.to_dict("records")})

    
    return JsonResponse({"data_series": json_data_series})
