import datetime
import subprocess

import docker


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
