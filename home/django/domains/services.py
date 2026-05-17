import datetime
import os
import signal
import subprocess
from pathlib import Path

import docker

from cloudlink.config import get_config

# home/ directory — build context for the cloudathome-acme image
_HOME_DIR = Path(__file__).resolve().parents[2]


class CertbotError(Exception):
    pass


class CertbotService:

    IMAGE = 'cloudathome-acme'
    WEBROOT = '/var/www/certbot'
    CERT_BASE = '/etc/letsencrypt'

    @classmethod
    def ensure_image(cls):
        """
        sudo docker run -it --rm -p 80:80   -v "/etc/letsencrypt:/etc/letsencrypt"   certbot/certbot certonly --standalone -d example.com
        :return:
        """
        client = docker.from_env()
        try:
            client.images.get(cls.IMAGE)
        except docker.errors.ImageNotFound:
            # Use the CLI rather than the SDK to avoid credential-store resolution
            # for unrelated registries (e.g. docker-credential-gcloud) during build.
            subprocess.run(
                ['docker', 'build', '-t', cls.IMAGE, '-f', 'nginx.dockerfile', '.'],
                cwd=str(_HOME_DIR),
                check=True,
            )

    @classmethod
    def issue_certificate(cls, domain, email, cert_output_path):
        client = docker.from_env()
        try:
            client.images.get(cls.IMAGE)
        except docker.errors.ImageNotFound:
            raise CertbotError(
                f'Docker image "{cls.IMAGE}" not found. '
                f'Build it first: docker build -t {cls.IMAGE} -f home/nginx.dockerfile home/'
            )
        container = client.containers.run(
            cls.IMAGE,
            detach=True,
            ports={'80/tcp': 80},
            volumes={cert_output_path: {'bind': cls.CERT_BASE, 'mode': 'rw'}},
        )
        try:
            exit_code, output = container.exec_run(
                [
                    'certbot', 'certonly',
                    '--webroot', '-w', cls.WEBROOT,
                    '-d', domain,
                    '--email', email,
                    '--agree-tos',
                    '--non-interactive',
                ],
            )
            if exit_code != 0:
                raise CertbotError(f'certbot failed (exit {exit_code}): {output.decode()}')
            return {
                'cert': f'{cert_output_path}/live/{domain}/fullchain.pem',
                'key': f'{cert_output_path}/live/{domain}/privkey.pem',
            }
        finally:
            container.stop()
            container.remove()

    @classmethod
    def check_certificate(cls, domain, cert_path):
        try:
            out = subprocess.check_output(
                ['openssl', 'x509', '-enddate', '-noout', '-in', cert_path],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            date_str = out.strip().split('=', 1)[1]
            return datetime.datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z').replace(
                tzinfo=datetime.timezone.utc
            )
        except Exception:
            return None


class TunnelService:

    @staticmethod
    def open_tunnel(tunnel_port, home_port):
        cfg = get_config()
        proc = subprocess.Popen([
            'ssh', '-N',
            '-R', f'{tunnel_port}:localhost:{home_port}',
            '-i', str(cfg.ssh.private_key_path),
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ExitOnForwardFailure=yes',
            '-p', str(cfg.ssh.port),
            f'{cfg.ssh.username}@{cfg.ssh.host}',
        ])
        return proc.pid

    @staticmethod
    def close_tunnel(pid):
        os.kill(pid, signal.SIGTERM)


