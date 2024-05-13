from django.db import models


class EIAHourlyDataCache(models.Model):
    
    cached_date = models.DateTimeField("date cached")

    # Following 4 constitute the cache key
    url_segment = models.CharField(max_length=200)
    facets = models.TextField() # store json blob
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    # TODO add unique constraint on the 4 of them?

    # the content, in CSV
    response_csv = models.TextField()
    
    

# separate cache for raw eia data and our derived data?

class HourlyGenerationMixCache(models.Model):
    # this is for post-import/export correction data
    # One row represents 
    generation_mwh = models.FloatField()
    emitted_tons_co2 = models.FloatField() # calculated from fuel type, emissions_per_kwh by type, and generation
    # Metric tons
    fuel_type = models.CharField(max_length=16)
    timestamp = models.DateTimeField() # we should do this with-timezone
    generating_ba = models.CharField(max_length=32)
    consuming_ba = models.CharField(max_length=32)
    # way to read this table:
    # each row is that x MWh were generated from Y fuel type in hour Z on balancing authority W and emitted
    # Q tons of CO2

#class HourlySomethingElseCache(models.Model):
#    timestamp = models.DateTimeField() # we should do this with-timezone
#    demand_mwh = models.FloatField()




