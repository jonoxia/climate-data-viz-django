from django.test import TestCase

from .utils import google_geocode
from .models import GeocodingAPICache


class GeocodeCacheTestCase(TestCase):
    def setUp(self):
        pass
    
    def test_geocode_cache(self):

        address = "72 N. Brainard Ave, La Grange, IL, 60525"
        
        cache_hit = GeocodingAPICache.objects.filter(address = address)
        self.assertEqual(len(cache_hit), 0)
        
        google_geocode(address)

        cache_hit = GeocodingAPICache.objects.filter(address = address)
        self.assertEqual(len(cache_hit), 1)
