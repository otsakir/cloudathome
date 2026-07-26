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
    """Builds the home/config.yaml contents for a registered home, and manages its API token."""

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

    @staticmethod
    def build_yaml(request, home) -> str:
        """Builds a template home/config.yaml for the given home.

        auth_token and private_key_path are left blank (with an explanatory comment
        above each) so the file fails to load until the user fills them in themselves
        -- this is a reusable template, not a one-time credential reveal.
        """
        port_base = tunnel_manager.get_home_port_base(home.home_index)
        tcp_port_base = tunnel_manager.get_home_tcp_public_port_base(home.home_index)

        config = {
            'cloudlink': {
                'cloudserver_url': request.build_absolute_uri('/').rstrip('/'),
                'auth_token': '',
                'home_slug': home.slug,
                'ssh': {
                    'host': request.get_host().split(':')[0],
                    'port': settings.CAH_SSH_PORT,
                    'username': home.get_username,
                    'private_key_path': '',
                },
                'ports': {
                    'base': port_base,
                    'count': tunnel_manager.config.PORTS_PER_HOME,
                },
                'tcp_ports': {
                    'base': tcp_port_base,
                    'count': tunnel_manager.config.TCP_PUBLIC_PORTS_PER_HOME,
                },
            },
            'database': 'db.sqlite3',
        }
        rendered = yaml.dump(config, default_flow_style=False, sort_keys=False)
        return HomeConfigService._annotate_blank_fields(rendered)

    @staticmethod
    def _annotate_blank_fields(rendered_yaml: str) -> str:
        lines = []
        for line in rendered_yaml.splitlines():
            stripped = line.lstrip()
            key = stripped.split(':', 1)[0]
            comment = _BLANK_FIELD_COMMENTS.get(key)
            if comment and stripped == f"{key}: ''":
                indent = line[:len(line) - len(stripped)]
                lines.append(f'{indent}# {comment}')
            lines.append(line)
        return '\n'.join(lines) + '\n'
