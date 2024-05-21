# URLs
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("energy_mix.json", views.energy_mix_json, name="energy_mix_json"),
    path("co2_intensity", views.co2_intensity, name="co2_intensity"),
    path("co2_intensity_json", views.co2_intensity_json, name="co2_intensity_json"),
    path("co2_intensity_boxplot", views.co2_intensity_boxplot, name="co2_intensity_boxplot"),
    path("co2_intensity_boxplot_json", views.co2_intensity_boxplot_json, name="co2_intensity_boxplot_json")
]
