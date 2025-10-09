from django.urls import path
from .views import ProxyMappingListCreateView

urlpatterns = [
    path('api/proxy-mappings/', ProxyMappingListCreateView.as_view(), name='proxy-mappings')
]
