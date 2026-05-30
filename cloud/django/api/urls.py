from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token
from .views import ProxyMappingListCreateView, ProxyMappingDestroyAPIView, ProxyInstanceAPIView, \
    HomeRetrieveDestroyApiView, HomeListCreateAPIView, ProxyMappingDumpView, HomeSyncView


urlpatterns = [
    path('api/auth/authtoken/', obtain_auth_token, name='api-token-auth'),
    path('api/homes/<slug:home_slug>/proxy-mappings/', ProxyMappingListCreateView.as_view(), name='proxy-mappings'),
    path('api/homes/<slug:home_slug>/proxy-mappings/<str:key>/', ProxyMappingDestroyAPIView.as_view(), name='delete-proxy-mapping'),

    path('api/proxy/instance/', ProxyInstanceAPIView.as_view(), name='proxy-instance'),

    path('api/homes/', HomeListCreateAPIView.as_view(), name='create-list-home'),
    path('api/homes/<slug:slug>/', HomeRetrieveDestroyApiView.as_view(), name='retrieve-delete-home'),

    path('api/admin/proxy-mappings/haproxy', ProxyMappingDumpView.as_view(), name='admin-proxy-mappings-haproxy'),

    path('api/admin/homes/sync', HomeSyncView.as_view(), name='admin-homes-sync'),
]
