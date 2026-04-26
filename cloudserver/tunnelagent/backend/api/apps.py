from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        from django.db import OperationalError, ProgrammingError
        from external.haproxy import HAProxyService
        from .models import ProxyMapping

        try:
            for mapping in ProxyMapping.objects.select_related('home').all():
                HAProxyService.add_mapping(mapping)
        except (OperationalError, ProgrammingError):
            # Table doesn't exist yet (e.g. during initial migrate)
            pass
        except Exception:
            # HAProxy not reachable (e.g. local dev with HAPROXY_ENABLED=False is silently skipped inside add_mapping)
            pass
