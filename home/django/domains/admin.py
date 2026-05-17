from django.contrib import admin

from domains.models import Domain, ProxyEntry


class ProxyEntryInline(admin.StackedInline):
    model = ProxyEntry
    extra = 0


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ('name', 'cert_status', 'cert_expiry')
    inlines = [ProxyEntryInline]


@admin.register(ProxyEntry)
class ProxyEntryAdmin(admin.ModelAdmin):
    list_display = ('cloudserver_host', 'domain', 'tunnel_port', 'home_port', 'scheme', 'tunnel_status')
