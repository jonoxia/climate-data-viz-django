from django.db import models


class AllPurposeCSVCache(models.Model):
    cache_function_name = models.TextField()
    cached_date = models.DateTimeField("date cached")
    key_params_json = models.TextField()
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    raw_csv = models.TextField()
    



