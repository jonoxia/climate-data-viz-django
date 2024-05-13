import json
import datetime

def find_matches(dsire, city, state, zip):

    now = datetime.datetime.now()

    def filter_func(record):
        # TODO - also look at utilities, counties.
        sectors = [sector["name"] for sector in record["Sectors"] if sector["selectable"]]

        return record["State"] == state and \
            ( city in record["Cities"] or len(record["Cities"]) == 0) and \
            ( zip in record["ZipCodes"] or len(record["ZipCodes"]) == 0) and \
            ( record['CategoryName'] == 'Financial Incentive') and \
            ("Commercial" in sectors or "Industrial" in sectors) and \
            ( record["StartDate"] == "" or datetime.datetime.strptime(record["StartDate"], '%m/%d/%Y') <= now) and \
            ( record["EndDate"] == "" or datetime.datetime.strptime(record["EndDate"], '%m/%d/%Y') >= now)

    # Date format for start/end dates is mm/dd/yyyy

    return [x for x in dsire["data"] if filter_func(x)]


dsire = json.loads(open("all_dsire_programs.json", "r").read())

matches = find_matches(dsire, "Mountain View", "California", "94043")

print( "\n\n\n\n".join([ x["Summary"] for x in matches ] ))
print( len(matches))
