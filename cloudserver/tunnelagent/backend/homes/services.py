import socket
import subprocess
from pathlib import Path

from django.conf import settings

from backend.settings import CAH_PUBLIC_KEY_STORAGE_PATH


MAP_FILE = '/usr/local/etc/haproxy/maps/sni_backends.map'


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
    def add_mapping(cls, mapping):
        cls._send_command(f'add map {MAP_FILE} {mapping.host} tunnel_{mapping.local_port}')

    @classmethod
    def remove_mapping(cls, mapping):
        cls._send_command(f'del map {MAP_FILE} {mapping.host}')

    @classmethod
    def sync_mappings(cls, mappings):
        cls._send_command(f'clear map {MAP_FILE}')
        for mapping in mappings:
            cls._send_command(f'add map {MAP_FILE} {mapping.host} tunnel_{mapping.local_port}')

    @classmethod
    def dump_mappings(cls):
        output = cls._send_command(f'show map {MAP_FILE}')
        entries = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) == 3:
                entries.append({'host': parts[1], 'backend': parts[2]})
        return entries


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
