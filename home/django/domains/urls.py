from django.urls import path

from domains.views import (
    AddDomainView,
    DeleteDomainView,
    DeleteProxyEntryView,
    DisconnectAllView,
    DomainDetailView,
    DomainListView,
    IssueCertificateView,
    ProxyEntryCreateView,
    ProxyEntryDetailView,
    SyncAllView,
    SyncEntryView,
    TcpProxyEntryCreateView,
    TunnelToggleView,
)

urlpatterns = [
    path('', DomainListView.as_view(), name='domain_list'),
    path('add/', AddDomainView.as_view(), name='add_domain'),
    path('sync/', SyncAllView.as_view(), name='sync_all'),
    path('disconnect/', DisconnectAllView.as_view(), name='disconnect_all'),
    path('<int:pk>/', DomainDetailView.as_view(), name='domain_detail'),
    path('<int:pk>/delete/', DeleteDomainView.as_view(), name='delete_domain'),
    path('<int:domain_pk>/proxy-entries/add/', ProxyEntryCreateView.as_view(), name='add_proxy_entry'),
    path('tcp-entries/add/', TcpProxyEntryCreateView.as_view(), name='add_tcp_proxy_entry'),
    path('proxy-entries/<int:pk>/', ProxyEntryDetailView.as_view(), name='proxy_entry_detail'),
    path('proxy-entries/<int:pk>/delete/', DeleteProxyEntryView.as_view(), name='delete_proxy_entry'),
    path('proxy-entries/<int:pk>/tunnel/', TunnelToggleView.as_view(), name='tunnel_toggle'),
    path('proxy-entries/<int:pk>/sync/', SyncEntryView.as_view(), name='sync_entry'),
    path('proxy-entries/<int:pk>/issue-certificate/', IssueCertificateView.as_view(), name='issue_certificate'),
]
