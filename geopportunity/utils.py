# Tim's code to look up incentive programs: https://app.hex.tech/8848a05c-8000-408c-9011-f87eca4333c5/hex/ab2f8a21-59ca-4c5b-8daa-de68058d545d/draft/logic  (DSIRE)

from django.conf import settings
import pandas as pd
import os
import re
import requests
import datetime
import json
from io import StringIO
from .models import GeocodingAPICache

def google_geocode(address):
    url = 'https://maps.googleapis.com/maps/api/geocode/json'

    # We will not commit the google maps API key to version control. If running on Koyeb then it's set
    # as an environment variable. To set this locally, do:
    # export GOOGLE_MAPS_API_KEY='xxxxxxxxxx'
    # before starting the django server.

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if api_key is None:
        api_key = settings.GOOGLE_MAPS_API_KEY
    assert api_key is not None

    # TODO check whether we already have a result for this address in our cache!!
    matches = GeocodingAPICache.objects.filter(address=address)
    if len(matches) > 0:
        print("Hit cache for {}".format(address))
        return matches[0].lat, matches[0].lon
    
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


            # Cache it:
            GeocodingAPICache.objects.create(
                address = address, lat=lat, lon=lng, date_cached=datetime.datetime.now())
            
            return lat, lng

        else:

            print(f"Error: {data['error_message']}")
            return 0, 0

    else:
        print("Failed to make the request.")
        return 0, 0



def find_egrid_subregion(UserInput):
    """
    Krista's code, copied from https://app.hex.tech/8848a05c-8000-408c-9011-f87eca4333c5/hex/981dbd8b-7072-4e79-8c28-acd2960fdd7f/draft/logic
    """
    # UserInput: a pandas data frame having one row per site,
    # with columns for zip code, lat, and lon.
    # Returns: UserInput data frame modified to add an "eGRID_subregion" column.

    # Load in the power profiler dataset of subregions and specify zip code column data types
    # Specifying column [0] as str and column [1] as int
    eGRIDsubregions_zip = pd.read_csv("geopportunity/raw_data/eGRIDsubregions_zipcode_lists.csv", dtype={0: str, 1: int})

    eGRIDsubregions_ziplists = eGRIDsubregions_zip.copy()

    # Rename columns as specified
    new_column_names = {
        "ZIP (character)": "zip_chara",
        "ZIP (numeric)": "zip_num",
        "eGRID Subregion #1": "eGrid_subregion",
    }
    eGRIDsubregions_ziplists.rename(columns=new_column_names, inplace=True)

    # EPA Power Profiler sub region has up to 3 zipcodes that can overlap on eGRID subregion
    # Convert first subregion column to a list.
    # For any row with more than one region, add all regions for that record to the list in the first subregion column.
    eGRIDsubregions_ziplists["eGrid_subregion"] = eGRIDsubregions_ziplists.apply(
        lambda row: [row["eGrid_subregion"]]
        + ([row["eGRID Subregion #2"]] if pd.notna(row["eGRID Subregion #2"]) else [])
        + ([row["eGRID Subregion #3"]] if pd.notna(row["eGRID Subregion #3"]) else []),
        axis=1,
    )

    # Drop the extra region columns
    eGRIDsubregions_ziplists.drop(
        columns=["eGRID Subregion #2", "eGRID Subregion #3"], inplace=True
    )

    UserInput["eGRID_subregion"] = pd.Series(dtype="str")
    for index, row in UserInput.iterrows():
        matching_rows = eGRIDsubregions_ziplists[
            eGRIDsubregions_ziplists["zip_chara"] == row["zip_chara"]
        ]
        if len(matching_rows) == 1:
            UserInput.at[index, "eGRID_subregion"] = matching_rows.iloc[0][
                "eGrid_subregion"
            ]

    # TODO: in the future, instead of reading and parsing subregions_zipcode_lists.csv anew each time,
    # we should parse it once and store result in a database table for fast lookup.
    return UserInput


def find_emisssions_for_grid_region(region):
    # TODO: finish copying this over.
    EmissionFactors_eGRID2022 = pd.read_csv("geopportunity/raw_data/CO₂ equivalent total output emission rate (lb_MWh), by eGRID subregion, 2022.csv")
    EmissionFactors_eGRID2022.columns = ["eGRID_subregion", "CO2e_lb/MWh"]

    



# Tim's Code:

def valid_zip_code(zip_code):
    # allows 3,4,5 and 5,3 digit zipcodes
    pattern = r'^\d{3,5}(?:-\d{4})?$'
    return re.match(pattern, str(zip_code)) is not None


STATES_ABBREV = "AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA, HI, ID, IL, IN, IA, KS, KY, LA, ME, MD, MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ, NM, NY, NC, ND, OH, OK, OR, PA, RI, SC, SD, TN, TX, UT, VT, VA, WA, WV, WI, WY, AS, DC, FM, GU, MH, MP, PW, PR, VI"

def generate_dsire_url(in_zip=None, state_abbreviation=None):
    dsire_url = "https://www.dsireusa.org/"
    if in_zip:
        in_zip = str(in_zip)
        if valid_zip_code(in_zip):
            dsire_url = f"https://programs.dsireusa.org/system/program?zipcode={in_zip}"
    elif state_abbreviation:
        if state_abbreviation.upper() in STATES_ABBREV:
            dsire_url = f"https://programs.dsireusa.org/system/program/{state_abbreviation.lower()}"
        else:
            print(f"Your state abbreviation not in:\n{STATES_ABBREV}")
    else:
        print(f"\nSomething amiss in use of: generate_dsire_url\n")
    return dsire_url


def tests_for_generate_dsire_url():
    test_my_zip_int = generate_dsire_url(in_zip=94901)
    test_my_zip_str = generate_dsire_url(in_zip='94901')
    test_zips = [test_my_zip_int, test_my_zip_str]

    test_my_abbrev_ok_lower = generate_dsire_url(state_abbreviation='ca')
    test_my_abbrev_ok_upper = generate_dsire_url(state_abbreviation='CA')
    test_states = [test_my_abbrev_ok_lower, test_my_abbrev_ok_upper]

    test_fail_zip_str = generate_dsire_url(in_zip='a')
    test_fail_non_zip = generate_dsire_url(in_zip=123456)
    test_fail_to_default = [test_fail_zip_str, test_fail_non_zip]

    tests = test_zips + test_states + test_fail_to_default
    [print(test) for test in tests]

