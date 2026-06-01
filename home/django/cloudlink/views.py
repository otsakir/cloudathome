from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import TemplateView, FormView

from cloudlink.config import get_config
from cloudlink.services import CloudServerClient, CloudServerError
from domains.models import Domain, ProxyEntry
from domains.services import TunnelService


class DashboardView(TemplateView):
    template_name = 'cloudlink/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cfg = get_config()
        context['config'] = cfg
        context['port_max'] = cfg.port_base + cfg.port_count - 1
        if cfg.tcp_port_base is not None and cfg.tcp_port_count is not None:
            context['tcp_port_max'] = cfg.tcp_port_base + cfg.tcp_port_count - 1

        domains = list(Domain.objects.select_related('proxy_entry').all())
        for domain in domains:
            try:
                entry = domain.proxy_entry
                entry.listening = (
                    TunnelService.is_home_port_open(entry.home_host, entry.home_port)
                    if entry.tunnel_status == ProxyEntry.TUNNEL_OPEN else None
                )
            except Exception:
                pass
        context['domains'] = domains

        tcp_entries = list(ProxyEntry.objects.filter(scheme=ProxyEntry.SCHEME_TCP))
        for entry in tcp_entries:
            entry.listening = (
                TunnelService.is_home_port_open(entry.home_host, entry.home_port)
                if entry.tunnel_status == ProxyEntry.TUNNEL_OPEN else None
            )
        context['tcp_entries'] = tcp_entries

        try:
            home = CloudServerClient().get_home()
            context['bandwidth_limit_kbps'] = home.get('bandwidth_limit_kbps')
            context['base_domains'] = home.get('base_domains', [])
        except Exception:
            context['bandwidth_limit_kbps'] = None
            context['base_domains'] = []

        from playbooks.certificate import IssueCertificatePlaybook
        context['playbooks'] = [
            {'name': IssueCertificatePlaybook.name,
             'description': IssueCertificatePlaybook.description,
             'url_name': 'playbook_issue_certificate'},
        ]
        return context


class SetBandwidthForm(forms.Form):
    bandwidth_limit_kbps = forms.IntegerField(
        min_value=100,
        max_value=10_000_000,
        required=False,
        label='Bandwidth limit (kbps)',
        help_text='Leave empty to remove the limit. Example: 5000 = 5 Mbps.',
    )


class AddBaseDomainForm(forms.Form):
    domain = forms.CharField(max_length=253, label='Domain name')


class AddBaseDomainView(FormView):
    template_name = 'cloudlink/add_base_domain.html'
    form_class = AddBaseDomainForm
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        try:
            CloudServerClient().add_base_domain(form.cleaned_data['domain'])
        except CloudServerError as e:
            form.add_error('domain', str(e))
            return self.form_invalid(form)
        return super().form_valid(form)


class RemoveBaseDomainView(View):
    def post(self, request, domain):
        try:
            CloudServerClient().remove_base_domain(domain)
        except CloudServerError as e:
            messages.error(request, str(e))
        return redirect('dashboard')


class SetBandwidthView(FormView):
    template_name = 'cloudlink/set_bandwidth.html'
    form_class = SetBandwidthForm
    success_url = reverse_lazy('dashboard')

    def get_initial(self):
        try:
            home = CloudServerClient().get_home()
            return {'bandwidth_limit_kbps': home.get('bandwidth_limit_kbps')}
        except Exception:
            return {}

    def form_valid(self, form):
        limit = form.cleaned_data.get('bandwidth_limit_kbps')
        try:
            CloudServerClient().update_bandwidth(limit)
        except CloudServerError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
        return super().form_valid(form)
