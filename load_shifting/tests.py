from django.test import TestCase
import datetime
import json
# Create your tests here.


# Write a test that asserts we can fill the db cache of the EIA data.

from .utils import get_hourly_eia_grid_mix
from .models import EIAHourlyDataCache

class EIACacheTestCase(TestCase):
    def setUp(self):
        pass
    
    def test_eia_cache(self):
        ba = "ERCO"  # CASO not working today for some reason????
        facets = json.dumps({"respondent": [ba]})
        start_date = datetime.datetime(year=2024, month=4, day=1)
        end_date = datetime.datetime(year=2024, month=4, day=30)
    
        cache_hit = EIAHourlyDataCache.objects.filter(
            url_segment = "fuel-type-data", start_date = start_date,
            end_date = end_date, facets=facets)

        self.assertEqual(cache_hit.count(), 0)
        result = get_hourly_eia_grid_mix(ba, start_date=start_date, end_date=end_date)

        cache_hit = EIAHourlyDataCache.objects.filter(
            url_segment = "fuel-type-data", start_date = start_date,
            end_date = end_date, facets=facets)

        self.assertEqual(cache_hit.count(), 1)
