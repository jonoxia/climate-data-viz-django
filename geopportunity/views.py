from django.shortcuts import render
from django.http import HttpResponse
import requests
import json
import os
import pandas as pd
import datetime
from geopportunity.utils import find_egrid_subregion, generate_dsire_url
from django.http import JsonResponse
from .forms import UploadFileForm


# Support CSV upload of multiple addresses OR multi-form for addresses
# 
# size based on emissions ( = the MWh/year you entered times the megatons CO2 based on your grid)

# for sure 4 other layers: (Wind, solar, geothermal, and energy efficiency)
# reach out to DOT for weirder maps


# Geocode API cache model:
#   - address, lat, lon, date cached
# TODO how are migrations run on server?



def proc_address_frame(user_data):


    # find_egrid_subregion takes a pandas frame:
    user_data = find_egrid_subregion(user_data)

    lats = []
    lons = []
    dsire_urls = []
    
    for idx, row in user_data.iterrows():
        lat, lon = google_geocode(row["street"] + ", " + row["city"] + ", " + row["state"] + " " + row["zip_chara"])

        dsire_url = generate_dsire_url(
            in_zip = row["zip_chara"],
            state_abbreviation = row["state"])

        lats.append(lat)
        lons.append(lon)
        dsire_urls.append(dsire_url)
        
    user_data["lat"] = lats
    user_data["lon"] = lons
    user_data["dsire_url"] = dsire_urls

    return user_data

 
def index(request):

    context = {"lat": "Unknown",
               "lon": "Unknown",
               "egrid_name": "Unknown"}
    for key in ["street", "city", "state", "zip"]:
        context[key] = request.GET.get(key, "")

    if "street" in request.GET and request.GET["street"] != "":
        user_data = pd.DataFrame(data = {
            "street": [ request.GET["street"]],
            "city": [ request.GET["city"]],
            "state": [ request.GET["state"]],
            "zip_chara": [ request.GET["zip"] ],
        })
        user_data = proc_address_frame(user_data)
        context["egrid_name"] = " ".join(user_data["eGRID_subregion"].values[0])
        context["lat"] = user_data["lat"].values[0]
        context["lon"] = user_data["lon"].values[0]
        context["dsire_url"] = user_data["dsire_url"].values[0]

    else:
        context["error_message"] = "You need to submit a zip code"

    return render(request, "geopportunity/index.html", context)


def upload_csv(request):

    sites = []
    errors = []
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        print(repr(request.POST))
        if form.is_valid():
            user_data = pd.read_csv(request.FILES["csv_file"],
                                    dtype={"street": str, "city": str, "state": str, "zip": str})
            columns_ok = True
            for required_field in ["street", "city", "state", "zip"]:
                if not required_field in user_data.columns:
                    errors.append("CSV missing required {} column".format(required_field))
                    columns_ok = False

            if columns_ok:
                user_data["zip_chara"] = user_data["zip"]
                user_data= proc_address_frame(user_data)

                sites = user_data.to_dict(orient="records")
                return HttpResponseRedirect("/thanks/")
        else:
            errors = ["Form invalid"]
    else:
        form = UploadFileForm()

    return render(request, "geopportunity/upload.html",
                  {"form": form, "sites": sites, "errors": ";".join(errors)})


