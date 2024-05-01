from django.shortcuts import render
from django.http import HttpResponse
import requests
import json
import os
import pandas as pd
from geopportunity.utils import find_egrid_subregion

# Support CSV upload of multiple addresses OR multi-form for addresses
# 
# size based on emissions ( = the MWh/year you entered times the megatons CO2 based on your grid)

# for sure 4 other layers: (Wind, solar, geothermal, and energy efficiency)
 # reach out to DOT for weirder maps



def google_geocode(address):
    url = 'https://maps.googleapis.com/maps/api/geocode/json'

    # We will not commit the google maps API key to version control. If running on Koyeb then it's set
    # as an environment variable. To set this locally, do:
    # export GOOGLE_MAPS_API_KEY='xxxxxxxxxx'
    # before starting the django server.

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    
    # private.
    params = {
        "address": address,
        "key": api_key
    }
    google_response = requests.get(url, params=params)

    if google_response.status_code == 200:
        google_data = google_response.json()
        if google_data["status"] == "OK":
            location = google_data["results"][0]["geometry"]["location"]
            lat = location["lat"]
            lng = location["lng"]
            return lat, lng

        else:

            print(f"Error: {data['error_message']}")
            return 0, 0

    else:
        print("Failed to make the request.")
        return 0, 0


 
def index(request):

    context = {"lat": "Unknown",
               "lon": "Unknown",
               "ba_name": "Unknown"}

    if "street" in request.GET and request.GET["street"] != "":

        lat, lon = google_geocode(request.GET["street"] + ", " + request.GET["city"] + ", " + request.GET["state"] + " " + request.GET["zip"])
        context["lat"] = lat
        context["lon"] = lon

        # find_egrid_subregion takes a pandas frame:
        user_data = pd.DataFrame(data = {"zip_chara": [ request.GET["zip"] ]})
        user_data = find_egrid_subregion(user_data)

        ba_names = user_data["eGRID_subregion"].values[0]
        context["ba_name"] = " ".join(ba_names)
    else:
        context["error_message"] = "You need to submit a zip code"

    return render(request, "geopportunity/index.html", context)
