import re
import socket
import subprocess
from pathlib import Path

import tldextract
from django.conf import settings

from cloudserver.settings import CAH_PUBLIC_KEY_STORAGE_PATH


SNI_MAP_FILE = '/usr/local/etc/haproxy/maps/sni_backends.map'
HTTP_MAP_FILE = '/usr/local/etc/haproxy/maps/host_http_backends.map'
TCP_MAP_FILE = '/usr/local/etc/haproxy/maps/tcp_backends.map'


class HAProxyService:

    @classmethod
    def _send_command(cls, command: str) -> str:
        if not settings.HAPROXY_ENABLED:
            return ''
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((settings.HAPROXY_API_HOST, settings.HAPROXY_API_PORT))
            s.sendall((command + '\n').encode())
            s.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        return b''.join(chunks).decode()

    @classmethod
    def add_mapping(cls, scheme, tunnel_port, host=None, public_port=None):
        if scheme == 'https':
            cls._send_command(f'add map {SNI_MAP_FILE} {host} tunnel_{tunnel_port}')
        elif scheme == 'http':
            cls._send_command(f'add map {HTTP_MAP_FILE} {host} http_tunnel_{tunnel_port}')
        elif scheme == 'tcp':
            cls._send_command(f'add map {TCP_MAP_FILE} {public_port} tunnel_{tunnel_port}')

    @classmethod
    def remove_mapping(cls, key):
        # key is a hostname (http/https) or public port number (tcp).
        # HAProxy treats del map on a missing key as a no-op, so we try all maps.
        cls._send_command(f'del map {SNI_MAP_FILE} {key}')
        cls._send_command(f'del map {HTTP_MAP_FILE} {key}')
        cls._send_command(f'del map {TCP_MAP_FILE} {key}')

    @classmethod
    def dump_mappings(cls):
        entries = []
        for map_file, scheme in (
            (SNI_MAP_FILE, 'https'),
            (HTTP_MAP_FILE, 'http'),
            (TCP_MAP_FILE, 'tcp'),
        ):
            output = cls._send_command(f'show map {map_file}')
            for line in output.splitlines():
                parts = line.split()
                if len(parts) == 3:
                    if scheme == 'tcp':
                        entries.append({'public_port': int(parts[1]), 'backend': parts[2], 'scheme': 'tcp'})
                    else:
                        entries.append({'host': parts[1], 'backend': parts[2], 'scheme': scheme})
        return entries

    @classmethod
    def get_used_ports(cls):
        """Return the set of tunnel ports currently registered across all HAProxy maps."""
        used = set()
        for entry in cls.dump_mappings():
            m = re.search(r'(\d+)$', entry['backend'])
            if m:
                used.add(int(m.group(1)))
        return used

    @classmethod
    def get_used_tcp_public_ports(cls):
        """Return the set of public TCP ports currently registered in the TCP map."""
        used = set()
        output = cls._send_command(f'show map {TCP_MAP_FILE}')
        for line in output.splitlines():
            parts = line.split()
            if len(parts) == 3:
                try:
                    used.add(int(parts[1]))
                except ValueError:
                    pass
        return used

    @classmethod
    def get_home_mappings(cls, port_base, port_count, tcp_public_port_base=None, tcp_public_port_count=None):
        """Return all active mappings for a home as dicts.

        HTTP/HTTPS entries: {host, tunnel_port, scheme}
        TCP entries:        {public_port, tunnel_port, scheme}
        """
        tunnel_ports = set(range(port_base, port_base + port_count))
        tcp_public_ports = set()
        if tcp_public_port_base is not None and tcp_public_port_count is not None:
            tcp_public_ports = set(range(tcp_public_port_base, tcp_public_port_base + tcp_public_port_count))

        result = []
        for entry in cls.dump_mappings():
            m = re.search(r'(\d+)$', entry['backend'])
            if not m:
                continue
            tunnel_port = int(m.group(1))
            scheme = entry['scheme']
            if scheme == 'tcp':
                pub_port = entry.get('public_port')
                if pub_port in tcp_public_ports:
                    result.append({'public_port': pub_port, 'tunnel_port': tunnel_port, 'scheme': 'tcp'})
            elif tunnel_port in tunnel_ports:
                result.append({'host': entry['host'], 'tunnel_port': tunnel_port, 'scheme': scheme})
        return result


class BaseDomainService:

    @staticmethod
    def validate(domain: str, exclude_home=None):
        """Validate a candidate base domain and raise ValueError on any violation."""
        from homes.models import HomeBaseDomain

        domain = domain.strip().lower()
        ext = tldextract.extract(domain)
        if not ext.domain or not ext.suffix:
            raise ValueError(f"'{domain}' is not a registrable domain")

        qs = HomeBaseDomain.objects.all()
        if exclude_home is not None:
            qs = qs.exclude(home=exclude_home)
        for existing in qs.values_list('domain', flat=True):
            if domain == existing:
                raise ValueError(f"'{domain}' is already registered")
            if domain.endswith('.' + existing):
                raise ValueError(f"'{domain}' falls under already-registered '{existing}'")
            if existing.endswith('.' + domain):
                raise ValueError(f"'{existing}' (another home) falls under '{domain}'")

        return domain

    @staticmethod
    def is_authorized(home, host: str) -> bool:
        """Return True if host is the base domain or a subdomain of one registered by this home."""
        host = host.lower()
        for bd in home.base_domains.values_list('domain', flat=True):
            if host == bd or host.endswith('.' + bd):
                return True
        return False

    @staticmethod
    def has_active_mappings(home, base_domain: str) -> bool:
        """Return True if HAProxy has any active mappings under base_domain for this home."""
        from homes.tunnels.manage_home import tunnel_manager
        port_base = tunnel_manager.get_home_port_base(home.home_index)
        tcp_port_base = tunnel_manager.get_home_tcp_public_port_base(home.home_index)
        mappings = HAProxyService.get_home_mappings(
            port_base,
            tunnel_manager.config.PORTS_PER_HOME,
            tcp_public_port_base=tcp_port_base,
            tcp_public_port_count=tunnel_manager.config.TCP_PUBLIC_PORTS_PER_HOME,
        )
        base_domain = base_domain.lower()
        for m in mappings:
            host = (m.get('host') or '').lower()
            if host and (host == base_domain or host.endswith('.' + base_domain)):
                return True
        return False


class ElevatedOperations:

    @staticmethod
    def add_home_user(home_id: int, username: str, public_key: str):
        public_key_filename = f'{username}{home_id}_public_key'
        public_key_filepath = Path(CAH_PUBLIC_KEY_STORAGE_PATH) / Path(public_key_filename)

        with open(public_key_filepath, 'w') as f:
            f.write(public_key)

        subprocess.run(['sudo', 'manage_home.py', 'add', username, str(home_id), '-p', public_key_filename], check=True)
        subprocess.run(['sudo', 'manage_home.py', 'reload'], check=True)

    @staticmethod
    def update_home_user_key(home_id: int, username: str, public_key: str):
        public_key_filename = f'{username}{home_id}_public_key'
        public_key_filepath = Path(CAH_PUBLIC_KEY_STORAGE_PATH) / Path(public_key_filename)

        with open(public_key_filepath, 'w') as f:
            f.write(public_key)

        subprocess.run(['sudo', 'manage_home.py', 'update-key', username, str(home_id), '-p', public_key_filename], check=True)

    @staticmethod
    def remove_home_user(home_id: int, username: str):
        subprocess.run(['sudo', 'manage_home.py', 'remove', username, str(home_id)], check=True)
        subprocess.run(['sudo', 'manage_home.py', 'reload'], check=True)

    @staticmethod
    def reload_tunnel_users():
        subprocess.run(['sudo', 'manage_home.py', 'reload'], check=True)

    @staticmethod
    def set_home_bandwidth(home_id: int, rate_kbps: int):
        subprocess.run(
            ['sudo', 'manage_home.py', 'bandwidth', 'set', str(home_id), '--rate', str(rate_kbps)],
            check=True,
        )

    @staticmethod
    def unset_home_bandwidth(home_id: int):
        subprocess.run(
            ['sudo', 'manage_home.py', 'bandwidth', 'unset', str(home_id)],
            check=True,
        )
