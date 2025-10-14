from django.urls import path
from .views import ProxyMappingListCreateView, ProxyMappingDestroyAPIView,ProxyInstanceAPIView

urlpatterns = [
    path('api/proxy-mappings/', ProxyMappingListCreateView.as_view(), name='proxy-mappings'),
    path('api/proxy-mappings/<slug:slug>/', ProxyMappingDestroyAPIView.as_view(), name='delete-proxy-mapping'),

    path('api/proxy/instance/', ProxyInstanceAPIView.as_view(), name='proxy-instance')
]
