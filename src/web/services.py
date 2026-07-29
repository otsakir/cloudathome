import yaml
from django.conf import settings
from rest_framework.authtoken.models import Token

from tunnels.ssh.manage_home import tunnel_manager

# Explanatory comments inserted above blank fields when a config is redacted,
# telling the user what to fill in and where to find it.
_BLANK_FIELD_COMMENTS = {
    'auth_token': 'Paste your API token here (shown at registration, or via "Rotate API token")',
    'private_key_path': 'Path to your private key on this machine, e.g. ~/.ssh/cloudathome_ed25519',
}


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
