from django.urls import path
from .views import ProxyMappingListCreateView, ProxyMappingDestroyAPIView, ProxyInstanceAPIView, \
    HomeRetrieveDestroyApiView, HomeListCreateAPIView, ProxyMappingSyncView, ProxyMappingDumpView


urlpatterns = [
    path('api/proxy-mappings/', ProxyMappingListCreateView.as_view(), name='proxy-mappings'),
    path('api/proxy-mappings/<slug:slug>/', ProxyMappingDestroyAPIView.as_view(), name='delete-proxy-mapping'),

    path('api/proxy/instance/', ProxyInstanceAPIView.as_view(), name='proxy-instance'),

    path('api/homes/', HomeListCreateAPIView.as_view(), name='create-list-home'),
    path('api/homes/<int:pk>', HomeRetrieveDestroyApiView.as_view(), name='retrieve-delete-home'),

    path('api/admin/proxy-mappings/sync', ProxyMappingSyncView.as_view(), name='admin-proxy-mappings-sync'),
    path('api/admin/proxy-mappings/haproxy', ProxyMappingDumpView.as_view(), name='admin-proxy-mappings-haproxy'),
]
