from django.urls import path
from .views import ProxyMappingListCreateView, ProxyMappingDestroyAPIView,ProxyInstanceAPIView, HomeCreateView, \
    HomeRetrieveApiView, HomeListAPIView


urlpatterns = [
    path('api/proxy-mappings/', ProxyMappingListCreateView.as_view(), name='proxy-mappings'),
    path('api/proxy-mappings/<slug:slug>/', ProxyMappingDestroyAPIView.as_view(), name='delete-proxy-mapping'),

    path('api/proxy/instance/', ProxyInstanceAPIView.as_view(), name='proxy-instance'),

    path('api/homes/', HomeListAPIView.as_view(), name='create-list-home'),
    path('api/homes/<int:pk>', HomeRetrieveApiView.as_view(), name='retrieve-delete-home'),
]
