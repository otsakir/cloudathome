import yaml
from django.conf import settings
from rest_framework.authtoken.models import Token

from core.services import HAProxyService
from core.ssh.manage_home import tunnel_manager

# Explanatory comments inserted above blank fields when a config is redacted,
# telling the user what to fill in and where to find it.
_BLANK_FIELD_COMMENTS = {
    'auth_token': 'Paste your API token here (shown at registration, or via "Rotate API token")',
    'private_key_path': 'Path to your private key on this machine, e.g. ~/.ssh/cloudathome_ed25519',
}


def cloudserver_url(request):
    """The URL homes should register against (cah.py's --cloudserver-url).

    Built from CAH_HOSTNAME rather than the request, so it's the canonical
    value regardless of how this page was reached: https whenever Django's
    HTTPS entrypoint is up (a cert is present), with the port only when it's
    non-standard. Falls back to the request's own host when CAH_HOSTNAME is
    unset (local dev, outside Docker)."""
    if not settings.CAH_HOSTNAME:
        return request.build_absolute_uri('/').rstrip('/')
    if HAProxyService.https_available():
        scheme, port, default_port = 'https', settings.CAH_HTTPS_PORT, 443
    else:
        scheme, port, default_port = 'http', settings.CAH_HTTP_PORT, 80
    suffix = '' if port == default_port else f':{port}'
    return f'{scheme}://{settings.CAH_HOSTNAME}{suffix}'


def ssh_host(request):
    """Host homes open their SSH tunnel to -- same host as cloudserver_url()."""
    return settings.CAH_HOSTNAME or request.get_host().split(':')[0]


class HomeConfigService:
    """Builds a home-side config.yaml template for a registered home, and manages its API token."""

    @staticmethod
    def get_or_create_token(user) -> Token:
        token, _ = Token.objects.get_or_create(user=user)
        return token

    @staticmethod
    def has_token(user) -> bool:
        return Token.objects.filter(user=user).exists()

    @staticmethod
    def rotate_token(user) -> Token:
        """Invalidates the existing token and issues a new one."""
        Token.objects.filter(user=user).delete()
        return Token.objects.create(user=user)
