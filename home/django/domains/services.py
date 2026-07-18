import datetime
import os
import shutil
import signal
import subprocess
from pathlib import Path

from cloudlink.config import get_config
from cloudlink.services import CloudServerClient, CloudServerError


class CertbotError(Exception):
    pass


class CertbotService:
    """Certbot state (config/work/logs) lives under the active profile's certbot_dir
    (get_config().certbot_dir), so concurrent profiles never share certbot's locks."""

    @classmethod
    def _config_dir(cls):
        return get_config().certbot_dir / 'config'

    @classmethod
    def _work_dir(cls):
        return get_config().certbot_dir / 'work'

    @classmethod
    def _logs_dir(cls):
        return get_config().certbot_dir / 'logs'

    @classmethod
    def obtain_certificate(cls, domain, email, home_port):
        """Run certbot standalone on home_port. The tunnel must already be open."""
        config_dir, work_dir, logs_dir = cls._config_dir(), cls._work_dir(), cls._logs_dir()
        for d in (config_dir, work_dir, logs_dir):
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
                '--config-dir', str(config_dir),
                '--work-dir', str(work_dir),
                '--logs-dir', str(logs_dir),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise CertbotError(f'certbot failed (exit {proc.returncode}):\n{proc.stderr}')

        cert_path = config_dir / 'live' / domain.name / 'fullchain.pem'
        expiry = cls.check_certificate(str(cert_path))
        domain.cert_status = domain.CERT_VALID
        domain.cert_expiry = expiry
        domain.cert_path = str(cert_path)
        domain.save()

        cfg = get_config()
        if domain.deploy_path:
            raw = Path(domain.deploy_path)
            effective_deploy = raw if raw.is_absolute() else (cfg.config_dir / raw).resolve()
        else:
            effective_deploy = cfg.certbot.deploy_path  # already an absolute Path or None
        if effective_deploy:
            cls._deploy_certificates(domain.name, effective_deploy)

    @classmethod
    def _deploy_certificates(cls, domain_name, deploy_path):
        """Copy fullchain.pem and privkey.pem to deploy_path/<domain_name>/."""
        src = cls._config_dir() / 'live' / domain_name
        dst = deploy_path / domain_name
        dst.mkdir(parents=True, exist_ok=True)
        for filename in ('fullchain.pem', 'privkey.pem', 'chain.pem', 'cert.pem'):
            src_file = src / filename
            if src_file.exists():
                shutil.copy2(src_file, dst / filename)

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
    def open_tunnel(tunnel_port, home_port, home_host='localhost'):
        cfg = get_config()
        if home_host not in ('localhost', '127.0.0.1', '::1') and not cfg.features.lan_forwarding:
            raise PermissionError(
                f'Tunnel to home network host "{home_host}" is blocked: '
                'enable features.lan_forwarding in config.yaml to allow it.'
            )
        proc = subprocess.Popen([
            'ssh', '-N',
            '-R', f'{tunnel_port}:{home_host}:{home_port}',
            '-i', str(cfg.ssh.private_key_path),
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ExitOnForwardFailure=yes',
            '-p', str(cfg.ssh.port),
            f'{cfg.ssh.username}@{cfg.ssh.host}',
        ])
        return proc.pid

    @staticmethod
    def is_home_port_open(home_host: str, home_port: int) -> bool | None:
        """Check if home_port is listening. Returns None for non-localhost targets."""
        if home_host not in ('localhost', '127.0.0.1', '::1'):
            return None
        import psutil
        return any(
            c.laddr.port == home_port and c.status == psutil.CONN_LISTEN
            for c in psutil.net_connections(kind='tcp')
        )

    @staticmethod
    def close_tunnel(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # process already gone, nothing to do


class SyncService:

    @staticmethod
    def sync_entry(entry):
        """Open tunnel + register cloud mapping for one entry. Idempotent."""
        from domains.models import ProxyEntry
        client = CloudServerClient()

        # Remove any stale cloud mapping before re-creating it.
        try:
            if entry.scheme == ProxyEntry.SCHEME_TCP:
                client.delete_proxy_mapping(str(entry.public_port))
            else:
                client.delete_proxy_mapping(entry.domain.name)
        except Exception:
            pass

        try:
            if entry.scheme == ProxyEntry.SCHEME_TCP:
                result = client.create_proxy_mapping('tcp', public_port=entry.public_port)
            else:
                result = client.create_proxy_mapping(entry.scheme, host=entry.domain.name)
            entry.tunnel_port = result['tunnel_port']
        except CloudServerError:
            entry.tunnel_status = ProxyEntry.TUNNEL_ERROR
            entry.save()
            raise

        if not entry.tunnel_pid or not TunnelService.is_running(entry.tunnel_pid):
            try:
                pid = TunnelService.open_tunnel(entry.tunnel_port, entry.home_port, entry.home_host)
                entry.tunnel_pid = pid
            except Exception:
                entry.tunnel_status = ProxyEntry.TUNNEL_ERROR
                entry.save()
                raise

        entry.tunnel_status = ProxyEntry.TUNNEL_OPEN
        entry.save()

    @staticmethod
    def sync_all():
        """Sync every ProxyEntry. Returns (succeeded, failed) counts."""
        from domains.models import ProxyEntry
        entries = list(ProxyEntry.objects.select_related('domain').all())
        succeeded = 0
        failed = 0
        for entry in entries:
            try:
                SyncService.sync_entry(entry)
                succeeded += 1
            except Exception:
                failed += 1
        return succeeded, failed

    @staticmethod
    def disconnect_entry(entry):
        """Close tunnel + remove cloud mapping for one entry."""
        from domains.models import ProxyEntry
        if entry.tunnel_pid:
            TunnelService.close_tunnel(entry.tunnel_pid)
        client = CloudServerClient()
        try:
            if entry.scheme == ProxyEntry.SCHEME_TCP:
                client.delete_proxy_mapping(str(entry.public_port))
            else:
                client.delete_proxy_mapping(entry.domain.name)
        except Exception:
            pass
        entry.tunnel_pid = None
        entry.tunnel_status = ProxyEntry.TUNNEL_CLOSED
        entry.save()

    @staticmethod
    def disconnect_all():
        """Close tunnels and remove cloud mappings for every ProxyEntry."""
        from domains.models import ProxyEntry
        for entry in ProxyEntry.objects.select_related('domain').all():
            SyncService.disconnect_entry(entry)


