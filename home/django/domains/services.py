import datetime
import os
import signal
import subprocess

import docker

from cloudlink.config import get_config
from cloudlink.services import CloudServerClient


class CertbotError(Exception):
    pass


class CertbotService:

    IMAGE = 'cloudathome-acme'
    WEBROOT = '/var/www/certbot'
    CERT_BASE = '/etc/letsencrypt'

    @classmethod
    def issue_certificate(cls, domain, email, cert_output_path):
        client = docker.from_env()
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


class OrchestratorError(Exception):
    pass


class DomainOrchestrator:

    @staticmethod
    def allocate_tunnel_port():
        from domains.models import ProxyEntry
        cfg = get_config()
        used = set(ProxyEntry.objects.values_list('tunnel_port', flat=True))
        try:
            return next(
                p for p in range(cfg.port_base, cfg.port_base + cfg.port_count)
                if p not in used
            )
        except StopIteration:
            raise OrchestratorError('No free tunnel ports available')

    @staticmethod
    def add_domain(name, email, cert_output_path):
        from domains.models import Domain, ProxyEntry

        # create home-side objects
        tunnel_port = DomainOrchestrator.allocate_tunnel_port()
        domain, _ = Domain.objects.get_or_create(name=name)
        entry = ProxyEntry.objects.create(
            domain=domain,
            cloudserver_host=name,
            tunnel_port=tunnel_port,
            home_port=80,
            scheme=ProxyEntry.SCHEME_HTTP,
        )
        client = CloudServerClient()
        cert_paths = None
        try:
            client.create_proxy_mapping(name, tunnel_port, 'http')
            pid = TunnelService.open_tunnel(tunnel_port, 80)
            entry.tunnel_pid = pid
            entry.tunnel_status = ProxyEntry.TUNNEL_OPEN
            entry.save()
            cert_paths = CertbotService.issue_certificate(name, email, cert_output_path)
        finally:
            if entry.tunnel_pid:
                try:
                    TunnelService.close_tunnel(entry.tunnel_pid)
                except Exception:
                    pass
            try:
                client.delete_proxy_mapping(name)
            except Exception:
                pass
            entry.delete()

        expiry = CertbotService.check_certificate(name, cert_paths['cert'])
        domain.cert_status = Domain.CERT_VALID
        domain.cert_expiry = expiry
        domain.cert_path = cert_paths['cert']
        domain.save()
        return domain
