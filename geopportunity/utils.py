# Tim's code to look up incentive programs: https://app.hex.tech/8848a05c-8000-408c-9011-f87eca4333c5/hex/ab2f8a21-59ca-4c5b-8daa-de68058d545d/draft/logic  (DSIRE)


import pandas as pd


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

    
