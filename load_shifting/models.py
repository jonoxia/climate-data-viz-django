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
    # this is for post-import/export corrected data
    # One row represents

    cached_date = models.DateTimeField("date cached")
    ba_name = models.CharField(max_length=32)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    calculated_csv = models.TextField()
    # each row of CSV is that x MWh were generated from Y fuel type in hour Z on balancing authority W and emitted
    # Q tons of CO2




