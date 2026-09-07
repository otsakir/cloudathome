from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tunnels.services import TLS_CERT_FILE, HAProxyService


DEFAULT_SCHEME_PORT = {'http': 80, 'https': 443}


def _url(scheme, hostname, port):
    port_suffix = '' if port == DEFAULT_SCHEME_PORT[scheme] else f':{port}'
    return f'{scheme}://{hostname}{port_suffix}/'


class Command(BaseCommand):
    help = (
        "Seeds the static HAProxy map entries that route settings.CAH_HOSTNAME to "
        "this instance's own Django backend(s). Fails startup if CAH_HOSTNAME is "
        "unset -- it's the only way to reach Django now, there's no separate "
        "published port. HAProxy's map files start empty on every container "
        "restart, so this needs to run on every startup, not just once -- unlike "
        "home mappings, nothing re-registers this one on the home's behalf. "
        "Reports which of Django's HTTP/HTTPS entrypoints ended up enabled."
    )

    def handle(self, *args, **options):
        if not settings.CAH_HOSTNAME:
            raise CommandError(
                'CAH_HOSTNAME must be set -- Django is reachable only through it '
                'now that CAH_API_PORT no longer exists.'
            )
        result = HAProxyService.ensure_admin_route()
        hostname = settings.CAH_HOSTNAME
        https_enabled = result['https_enabled']

        http_url = _url('http', hostname, settings.CAH_HTTP_PORT)
        self.stdout.write(f'Django HTTP:  enabled at {http_url}' + (' (redirects to HTTPS)' if https_enabled else ''))
        if https_enabled:
            https_url = _url('https', hostname, settings.CAH_HTTPS_PORT)
            self.stdout.write(f'Django HTTPS: enabled at {https_url}')
        else:
            self.stdout.write(f'Django HTTPS: disabled -- no cert found at {TLS_CERT_FILE}')
