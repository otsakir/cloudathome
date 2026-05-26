import re
import socket
import subprocess
from pathlib import Path

from django.conf import settings

from cloudserver.settings import CAH_PUBLIC_KEY_STORAGE_PATH


SNI_MAP_FILE = '/usr/local/etc/haproxy/maps/sni_backends.map'
HTTP_MAP_FILE = '/usr/local/etc/haproxy/maps/host_http_backends.map'


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
    def add_mapping(cls, host, tunnel_port, scheme):
        if scheme == 'https':
            map_file, backend = SNI_MAP_FILE, f'tunnel_{tunnel_port}'
        else:
            map_file, backend = HTTP_MAP_FILE, f'http_tunnel_{tunnel_port}'
        cls._send_command(f'add map {map_file} {host} {backend}')

    @classmethod
    def remove_mapping(cls, host):
        # Remove from both maps; HAProxy treats del map on a missing key as a no-op.
        cls._send_command(f'del map {SNI_MAP_FILE} {host}')
        cls._send_command(f'del map {HTTP_MAP_FILE} {host}')

    @classmethod
    def dump_mappings(cls):
        entries = []
        for map_file in (SNI_MAP_FILE, HTTP_MAP_FILE):
            output = cls._send_command(f'show map {map_file}')
            for line in output.splitlines():
                parts = line.split()
                if len(parts) == 3:
                    entries.append({'host': parts[1], 'backend': parts[2]})
        return entries

    @classmethod
    def get_used_ports(cls):
        """Return the set of tunnel ports currently registered in HAProxy maps."""
        used = set()
        for entry in cls.dump_mappings():
            m = re.search(r'(\d+)$', entry['backend'])
            if m:
                used.add(int(m.group(1)))
        return used

    @classmethod
    def get_home_mappings(cls, port_base, port_count):
        """Return entries for a home's port range as {host, tunnel_port, scheme} dicts."""
        ports = set(range(port_base, port_base + port_count))
        result = []
        for entry in cls.dump_mappings():
            m = re.search(r'(\d+)$', entry['backend'])
            if m:
                port = int(m.group(1))
                if port in ports:
                    scheme = 'http' if entry['backend'].startswith('http_tunnel_') else 'https'
                    result.append({'host': entry['host'], 'tunnel_port': port, 'scheme': scheme})
        return result


class ElevatedOperations:

    @staticmethod
    def add_home_user(home_id: int, username: str, public_key: str):
        public_key_filename = f'{username}{home_id}_public_key'
        public_key_filepath = Path(CAH_PUBLIC_KEY_STORAGE_PATH) / Path(public_key_filename)

        with open(public_key_filepath, 'w') as f:
            f.write(public_key)

        subprocess.run(['sudo', 'manage_tunnel.py', 'add', username, str(home_id), '-p', public_key_filename], check=True)
        subprocess.run(['sudo', 'manage_tunnel.py', 'reload'], check=True)

    @staticmethod
    def update_home_user_key(home_id: int, username: str, public_key: str):
        public_key_filename = f'{username}{home_id}_public_key'
        public_key_filepath = Path(CAH_PUBLIC_KEY_STORAGE_PATH) / Path(public_key_filename)

        with open(public_key_filepath, 'w') as f:
            f.write(public_key)

        subprocess.run(['sudo', 'manage_tunnel.py', 'update-key', username, str(home_id), '-p', public_key_filename], check=True)

    @staticmethod
    def remove_home_user(home_id: int, username: str):
        subprocess.run(['sudo', 'manage_tunnel.py', 'remove', username, str(home_id)], check=True)
        subprocess.run(['sudo', 'manage_tunnel.py', 'reload'], check=True)

    @staticmethod
    def reload_tunnel_users():
        subprocess.run(['sudo', 'manage_tunnel.py', 'reload'], check=True)
