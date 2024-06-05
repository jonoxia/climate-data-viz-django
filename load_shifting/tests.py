from django.test import TestCase
import datetime
import json
import os
# Create your tests here.


# Write a test that asserts we can fill the db cache of the EIA data.

from .utils import get_hourly_eia_grid_mix, compute_hourly_consumption_by_source_ba, compute_hourly_fuel_mix_after_import_export, cache_wrapped_hourly_gen_mix_by_ba_and_type
from .models import AllPurposeCSVCache

class EIACacheTestCase(TestCase):
    def setUp(self):
        pass
    
    def test_eia_cache(self):
        ba = "CISO"
        start_date = datetime.datetime(year=2024, month=4, day=1)
        end_date = datetime.datetime(year=2024, month=4, day=30)

        params_json = {"url_segment": "fuel-type-data",
                       "facets": {"respondent": [ba]}}
        cache_hit = AllPurposeCSVCache.objects.filter(
            cache_function_name = "cache_wrapped_get_eia_timeseries",
            key_params_json = json.dumps(params_json),
            start_date = start_date,
            end_date = end_date)

        self.assertEqual(cache_hit.count(), 0)
        result = get_hourly_eia_grid_mix([ba], start_date=start_date, end_date=end_date)

        cache_hit = AllPurposeCSVCache.objects.filter(
            cache_function_name = "cache_wrapped_get_eia_timeseries",
            key_params_json = json.dumps(params_json),
             start_date = start_date,
            end_date = end_date)

        self.assertEqual(cache_hit.count(), 1)

class CO2CalculationTestCase(TestCase):
    def setUp(self):
        pass

    def test_co2_intensity(self):
        # what's the best 
        pass

# TODO class that tests views

class HouseModelingTestCase(TestCase):
    def setUp(self):
        pass

    def test_house_simulation(self):
        pass


class ImportExportBATestCase(TestCase):
    def setUp(self):
        # Pre-load some saved JSON into the cache so we don't actually hit EIA API when testing:
        cache_metadatas = {
            "fuel-type-data_1_respondents.csv": {
                "url_segment": "fuel-type-data",
                "facets": {"respondent": ["CISO"]},
                "value_column_name": "Generation (MWh)",
                "frequency": "local-hourly",
                "include_timezone": False
            },
            "interchange-data_0_respondents.csv": {
                "url_segment": "interchange-data",
                "facets": {"toba": ["CISO"]},
                "value_column_name": "Interchange to local BA (MWh)",
                "frequency": "local-hourly",
                "include_timezone": False
            },
            "region-data_1_respondents.csv": {
                "url_segment": "region-data",
                "facets": {"respondent": ["CISO"], "type": ["D", "NG", "TI"]},
                "value_column_name": "Demand (MWh)",
                "frequency": "local-hourly",
                "include_timezone": False
            },
            "fuel-type-data_11_respondents.csv": {
                "url_segment": "fuel-type-data",
                "facets": {"respondent": ["AZPS", "BANC", "BPAT", "IID", "LDWP", "NEVP", "PACW", "SRP", "TIDC", "WALC", "CISO"]},
                "value_column_name": "Generation (MWh)",
                "frequency": "local-hourly",
                "include_timezone": False
            }
        }

        for cache_file_name in cache_metadatas.keys():
            with open(os.path.join("load_shifting/eia_caches_for_testing", cache_file_name)) as infile:
                cache_metadata = {}
                cache_metadata["key_params_json"] = json.dumps(cache_metadatas[cache_file_name])
                cache_metadata["raw_csv"] = infile.read()
                cache_metadata["start_date"] = datetime.datetime(year=2024, month=4, day=1)
                cache_metadata["end_date"] = datetime.datetime(year=2024, month=4, day=30)
                cache_metadata["cached_date"] = datetime.datetime.now()
                cache_metadata["cache_function_name"] = "cache_wrapped_get_eia_timeseries"
                new_cache = AllPurposeCSVCache.objects.create(**cache_metadata)
                new_cache.save()

        

    def test_import_export_correction(self):
        start_date = datetime.datetime(year=2024, month=4, day=1)
        end_date = datetime.datetime(year=2024, month=4, day=30)

        consumption_by_ba = compute_hourly_consumption_by_source_ba("CISO", start_date, end_date)
        self.assertEqual(set(consumption_by_ba.columns), set(["timestamp", "fromba", "Power consumed locally (MWh)"]))
        usage_by_ba_and_type = compute_hourly_fuel_mix_after_import_export("CISO", consumption_by_ba, start_date, end_date)
        self.assertEqual(set(usage_by_ba_and_type.columns),
                         set(['timestamp', 'emissions_per_kwh', 'Usage (MWh)', 'emissions', 'generation_type', 'fromba']))


    def test_the_import_export_is_cached(self):
        
        ba = "CISO"
        start_date = datetime.datetime(year=2024, month=4, day=1)
        end_date = datetime.datetime(year=2024, month=4, day=30)
    
        cache_hit = AllPurposeCSVCache.objects.filter(
            cache_function_name = "cache_wrapped_hourly_gen_mix_by_ba_and_type",
            key_params_json = json.dumps({"ba_name": ba}),
            start_date = start_date,
            end_date = end_date)

        self.assertEqual(cache_hit.count(), 0)
        result = cache_wrapped_hourly_gen_mix_by_ba_and_type(
            ba_name=ba,
            start_date=start_date,
            end_date=end_date)

        cache_hit = AllPurposeCSVCache.objects.filter(
            cache_function_name = "cache_wrapped_hourly_gen_mix_by_ba_and_type",
            key_params_json = json.dumps({"ba_name": ba}),
            start_date = start_date,
            end_date = end_date)

        self.assertEqual(cache_hit.count(), 1)
