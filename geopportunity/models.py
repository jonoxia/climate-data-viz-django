from django.db import models

# Create your models here.

class GeocodingAPICache(models.Model):
    address = models.CharField(max_length=128)
    lat = models.FloatField()
    lon = models.FloatField()
    date_cached = models.DateTimeField()
