from cloudlink.services import CloudServerClient
from domains.models import Domain, ProxyEntry
from domains.services import CertbotService, TunnelService
from playbooks.base import Playbook, PlaybookResult, StepResult


class IssueCertificatePlaybook(Playbook):
    name = 'Issue certificate'
    description = (
        'Registers a temporary HTTP proxy mapping, opens an SSH tunnel, '
        'runs certbot to obtain a TLS certificate, then cleans up. '
        'On failure the proxy entry is left in place so you can investigate.'
    )

    def run(self, domain_name, email, home_port) -> PlaybookResult:
        steps = []
        domain = None
        entry = None

        # ── Step 1: get or create Domain record ──────────────────────────
        try:
            domain, created = Domain.objects.get_or_create(name=domain_name)
            steps.append(StepResult(
                'Get or create domain record',
                'ok',
                f'{"Created" if created else "Found existing"} domain {domain_name}',
            ))
        except Exception as e:
            steps.append(StepResult('Get or create domain record', 'error', str(e)))
            return PlaybookResult(steps=steps)

        # ── Step 2: create or reuse HTTP proxy entry ──────────────────────
        try:
            try:
                existing = domain.proxy_entry
                if existing.scheme != ProxyEntry.SCHEME_HTTP:
                    raise Exception(
                        f'Domain already has a {existing.scheme.upper()} proxy entry — remove it first.'
                    )
                entry = existing
                steps.append(StepResult(
                    'HTTP proxy entry',
                    'ok',
                    f'Reusing existing entry (tunnel port {entry.tunnel_port})',
                ))
            except ProxyEntry.DoesNotExist:
                if ProxyEntry.objects.filter(home_host='localhost', home_port=home_port).exists():
                    raise Exception(
                        f'Local port {home_port} is already used by another proxy entry.'
                    )
                result = CloudServerClient().create_proxy_mapping('http', host=domain_name)
                entry = ProxyEntry.objects.create(
                    domain=domain,
                    tunnel_port=result['tunnel_port'],
                    home_host='localhost',
                    home_port=home_port,
                    scheme=ProxyEntry.SCHEME_HTTP,
                )
                steps.append(StepResult(
                    'Register HTTP proxy mapping',
                    'ok',
                    f'Tunnel port {entry.tunnel_port} allocated',
                ))
        except Exception as e:
            steps.append(StepResult('Register HTTP proxy mapping', 'error', str(e)))
            return PlaybookResult(steps=steps, entry=entry)

        # ── Step 3: open SSH tunnel ───────────────────────────────────────
        try:
            if (entry.tunnel_status == ProxyEntry.TUNNEL_OPEN
                    and entry.tunnel_pid
                    and TunnelService.is_running(entry.tunnel_pid)):
                steps.append(StepResult(
                    'Open SSH tunnel', 'ok',
                    f'Reusing existing tunnel (pid {entry.tunnel_pid})',
                ))
            else:
                pid = TunnelService.open_tunnel(entry.tunnel_port, home_port)
                entry.tunnel_pid = pid
                entry.tunnel_status = ProxyEntry.TUNNEL_OPEN
                entry.save()
                steps.append(StepResult('Open SSH tunnel', 'ok', f'pid {pid}'))
        except Exception as e:
            entry.tunnel_status = ProxyEntry.TUNNEL_ERROR
            entry.save()
            steps.append(StepResult('Open SSH tunnel', 'error', str(e)))
            return PlaybookResult(steps=steps, entry=entry)

        # ── Step 4: run certbot ───────────────────────────────────────────
        try:
            CertbotService.obtain_certificate(domain, email, home_port)
            expiry = domain.cert_expiry.strftime('%Y-%m-%d') if domain.cert_expiry else 'unknown'
            steps.append(StepResult('Issue certificate', 'ok', f'Valid until {expiry}'))
        except Exception as e:
            steps.append(StepResult('Issue certificate', 'error', str(e)))
            return PlaybookResult(steps=steps, entry=entry)

        # ── Step 5: cleanup (success path only) ───────────────────────────
        try:
            if entry.tunnel_pid:
                TunnelService.close_tunnel(entry.tunnel_pid)
            CloudServerClient().delete_proxy_mapping(domain_name)
            entry.delete()
            entry = None
            steps.append(StepResult('Remove temporary HTTP proxy entry', 'ok', ''))
        except Exception as e:
            steps.append(StepResult('Remove temporary HTTP proxy entry', 'error', str(e)))

        return PlaybookResult(steps=steps, entry=entry)
