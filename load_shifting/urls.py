# URLs
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("energy_mix.json", views.energy_mix_json, name="energy_mix_json"),
    #path("upload_csv", views.upload_csv, name="upload_csv"),
]
