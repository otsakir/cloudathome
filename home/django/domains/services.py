import datetime
import os
import signal
import subprocess
from pathlib import Path

from cloudlink.config import get_config

# home/ directory
_HOME_DIR = Path(__file__).resolve().parents[2]


class CertbotError(Exception):
    pass


class CertbotService:

    CONFIG_DIR = _HOME_DIR / 'certbot' / 'config'
    WORK_DIR   = _HOME_DIR / 'certbot' / 'work'
    LOGS_DIR   = _HOME_DIR / 'certbot' / 'logs'

    @classmethod
    def obtain_certificate(cls, domain, email, home_port):
        """Run certbot standalone on home_port. The tunnel must already be open."""
        for d in (cls.CONFIG_DIR, cls.WORK_DIR, cls.LOGS_DIR):
            d.mkdir(parents=True, exist_ok=True)

        proc = subprocess.run(
            [
                'certbot', 'certonly',
                '--standalone',
                '--non-interactive',
                '--agree-tos',
                '-m', email,
                '-d', domain.name,
                '--http-01-port', str(home_port),
                '--config-dir', str(cls.CONFIG_DIR),
                '--work-dir', str(cls.WORK_DIR),
                '--logs-dir', str(cls.LOGS_DIR),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise CertbotError(f'certbot failed (exit {proc.returncode}):\n{proc.stderr}')

        cert_path = cls.CONFIG_DIR / 'live' / domain.name / 'fullchain.pem'
        expiry = cls.check_certificate(str(cert_path))
        domain.cert_status = domain.CERT_VALID
        domain.cert_expiry = expiry
        domain.cert_path = str(cert_path)
        domain.save()

    @classmethod
    def check_certificate(cls, cert_path):
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
    def is_running(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

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
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # process already gone, nothing to do


