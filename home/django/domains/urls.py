from django.urls import path

from domains.views import (
    AddDomainView,
    DeleteDomainView,
    DeleteProxyEntryView,
    DomainDetailView,
    DomainListView,
    ProxyEntryCreateView,
    ProxyEntryDetailView,
    TunnelToggleView,
)

urlpatterns = [
    path('', DomainListView.as_view(), name='domain_list'),
    path('add/', AddDomainView.as_view(), name='add_domain'),
    path('<int:pk>/', DomainDetailView.as_view(), name='domain_detail'),
    path('<int:pk>/delete/', DeleteDomainView.as_view(), name='delete_domain'),
    path('<int:domain_pk>/proxy-entries/add/', ProxyEntryCreateView.as_view(), name='add_proxy_entry'),
    path('proxy-entries/<int:pk>/', ProxyEntryDetailView.as_view(), name='proxy_entry_detail'),
    path('proxy-entries/<int:pk>/delete/', DeleteProxyEntryView.as_view(), name='delete_proxy_entry'),
    path('proxy-entries/<int:pk>/tunnel/', TunnelToggleView.as_view(), name='tunnel_toggle'),
]
