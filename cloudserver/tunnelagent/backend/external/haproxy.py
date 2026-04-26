import socket
from django.conf import settings

MAP_FILE = '/usr/local/etc/haproxy/sni_backends.map'


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
