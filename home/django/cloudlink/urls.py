from django.urls import path
from .views import DashboardView, SetBandwidthView

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('bandwidth/', SetBandwidthView.as_view(), name='set_bandwidth'),
]
