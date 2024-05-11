from django.shortcuts import render

from .utils import get_hourly_eia_net_demand_and_generation, get_hourly_eia_interchange, get_hourly_eia_grid_mix


def index(request):
    context = {}
    return render(request, "load_shifting/index.html", context)
