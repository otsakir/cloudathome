from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView, DetailView, FormView

from cloudlink.services import CloudServerClient, CloudServerError
from domains.forms import AddDomainForm, IssueCertificateForm, ProxyEntryForm, TcpProxyEntryForm
from domains.models import Domain, ProxyEntry
from domains.services import CertbotError, CertbotService, SyncService, TunnelService


def _delete_proxy_entry(entry):
    """Close the tunnel, remove the cloud mapping, and delete the local record."""
    if entry.tunnel_pid:
        TunnelService.close_tunnel(entry.tunnel_pid)
    client = CloudServerClient()
    try:
        key = str(entry.public_port) if entry.scheme == ProxyEntry.SCHEME_TCP else entry.domain.name
        client.delete_proxy_mapping(key)
    except Exception:
        pass
    entry.delete()


class DomainListView(ListView):
    model = Domain
    template_name = 'domains/domain_list.html'
    context_object_name = 'domains'

    def get_queryset(self):
        return Domain.objects.select_related('proxy_entry').all()

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs)


class AddDomainView(FormView):
    template_name = 'domains/add_domain.html'
    form_class = AddDomainForm

    def form_valid(self, form):
        domain, _ = Domain.objects.get_or_create(name=form.cleaned_data['name'])
        return redirect('domain_detail', pk=domain.pk)


class DomainDetailView(DetailView):
    model = Domain
    template_name = 'domains/domain_detail.html'


class DeleteDomainView(View):
    def get(self, request, pk):
        domain = get_object_or_404(Domain, pk=pk)
        return render(request, 'domains/delete_domain.html', {'domain': domain})

    def post(self, request, pk):
        domain = get_object_or_404(Domain, pk=pk)
        try:
            _delete_proxy_entry(domain.proxy_entry)
        except ProxyEntry.DoesNotExist:
            pass
        domain.delete()
        return redirect('domain_list')


class ProxyEntryCreateView(FormView):
    template_name = 'domains/add_proxy_entry.html'
    form_class = ProxyEntryForm

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.domain = get_object_or_404(Domain, pk=kwargs['domain_pk'])

    def get_context_data(self, **kwargs):
        from cloudlink.config import get_config
        context = super().get_context_data(**kwargs)
        context['domain'] = self.domain
        context['lan_forwarding'] = get_config().features.lan_forwarding
        return context

    def form_valid(self, form):
        from cloudlink.config import get_config
        cfg = get_config()
        if cfg.features.lan_forwarding:
            home_host = form.cleaned_data.get('home_host') or 'localhost'
        else:
            home_host = 'localhost'
        home_port = form.cleaned_data['home_port']

        if ProxyEntry.objects.filter(home_host=home_host, home_port=home_port).exists():
            form.add_error(None, f'{home_host}:{home_port} is already used by another proxy entry.')
            return self.form_invalid(form)

        client = CloudServerClient()
        try:
            result = client.create_proxy_mapping(form.cleaned_data['scheme'], host=self.domain.name)
        except CloudServerError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        entry = ProxyEntry.objects.create(
            domain=self.domain,
            tunnel_port=result['tunnel_port'],
            home_host=home_host,
            home_port=home_port,
            scheme=form.cleaned_data['scheme'],
        )
        return redirect('proxy_entry_detail', pk=entry.pk)


class ProxyEntryDetailView(DetailView):
    model = ProxyEntry
    template_name = 'domains/proxy_entry_detail.html'

    def get_object(self, queryset=None):
        entry = super().get_object(queryset)
        # Correct stale "open" status if the SSH process is no longer running
        if entry.tunnel_status == ProxyEntry.TUNNEL_OPEN and entry.tunnel_pid:
            if not TunnelService.is_running(entry.tunnel_pid):
                entry.tunnel_pid = None
                entry.tunnel_status = ProxyEntry.TUNNEL_CLOSED
                entry.save()
        return entry

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self.object
        context['home_port_open'] = TunnelService.is_home_port_open(entry.home_host, entry.home_port)
        return context


class IssueCertificateView(FormView):
    template_name = 'domains/issue_certificate.html'
    form_class = IssueCertificateForm

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.entry = get_object_or_404(ProxyEntry, pk=kwargs['pk'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['entry'] = self.entry
        return context

    def form_valid(self, form):
        try:
            CertbotService.obtain_certificate(
                self.entry.domain,
                form.cleaned_data['email'],
                self.entry.home_port,
            )
        except CertbotError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
        return redirect('proxy_entry_detail', pk=self.entry.pk)


class TcpProxyEntryCreateView(FormView):
    template_name = 'domains/add_tcp_proxy_entry.html'
    form_class = TcpProxyEntryForm

    def get_context_data(self, **kwargs):
        from cloudlink.config import get_config
        context = super().get_context_data(**kwargs)
        cfg = get_config()
        context['tcp_port_base'] = cfg.tcp_port_base
        context['tcp_port_count'] = cfg.tcp_port_count
        if cfg.tcp_port_base is not None and cfg.tcp_port_count is not None:
            context['tcp_port_max'] = cfg.tcp_port_base + cfg.tcp_port_count - 1
        context['lan_forwarding'] = cfg.features.lan_forwarding
        return context

    def form_valid(self, form):
        from cloudlink.config import get_config
        cfg = get_config()
        public_port = form.cleaned_data['public_port']
        home_port = form.cleaned_data['home_port']
        home_host = form.cleaned_data.get('home_host') or 'localhost'
        if not cfg.features.lan_forwarding:
            home_host = 'localhost'

        if cfg.tcp_port_base is not None and cfg.tcp_port_count is not None:
            if not (cfg.tcp_port_base <= public_port < cfg.tcp_port_base + cfg.tcp_port_count):
                form.add_error('public_port', f'Must be in range {cfg.tcp_port_base}–{cfg.tcp_port_base + cfg.tcp_port_count - 1}.')
                return self.form_invalid(form)

        if ProxyEntry.objects.filter(public_port=public_port).exists():
            form.add_error('public_port', 'This public port is already registered.')
            return self.form_invalid(form)

        if ProxyEntry.objects.filter(home_host=home_host, home_port=home_port).exists():
            form.add_error(None, f'{home_host}:{home_port} is already used by another proxy entry.')
            return self.form_invalid(form)

        client = CloudServerClient()
        try:
            result = client.create_proxy_mapping('tcp', public_port=public_port)
        except CloudServerError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        entry = ProxyEntry.objects.create(
            scheme=ProxyEntry.SCHEME_TCP,
            public_port=public_port,
            tunnel_port=result['tunnel_port'],
            home_host=home_host,
            home_port=home_port,
        )
        return redirect('proxy_entry_detail', pk=entry.pk)


class DeleteProxyEntryView(View):
    def post(self, request, pk):
        entry = get_object_or_404(ProxyEntry, pk=pk)
        domain_pk = entry.domain_id
        _delete_proxy_entry(entry)
        if domain_pk:
            return redirect('domain_detail', pk=domain_pk)
        return redirect('domain_list')


class SyncAllView(View):
    def post(self, request):
        succeeded, failed = SyncService.sync_all()
        if failed:
            messages.warning(request, f'Connect all: {succeeded} connected, {failed} failed')
        else:
            messages.success(request, f'All tunnels connected ({succeeded} entries)')
        return redirect('dashboard')


class DisconnectAllView(View):
    def post(self, request):
        SyncService.disconnect_all()
        messages.success(request, 'All tunnels disconnected')
        return redirect('dashboard')


class SyncEntryView(View):
    def post(self, request, pk):
        entry = get_object_or_404(ProxyEntry, pk=pk)
        try:
            SyncService.sync_entry(entry)
            messages.success(request, 'Entry synced successfully')
        except Exception as e:
            messages.error(request, f'Sync failed: {e}')
        return redirect('proxy_entry_detail', pk=entry.pk)


class TunnelToggleView(View):
    def post(self, request, pk):
        entry = get_object_or_404(ProxyEntry, pk=pk)
        if entry.tunnel_status == ProxyEntry.TUNNEL_OPEN:
            if entry.tunnel_pid:
                TunnelService.close_tunnel(entry.tunnel_pid)
            entry.tunnel_pid = None
            entry.tunnel_status = ProxyEntry.TUNNEL_CLOSED
        else:
            try:
                pid = TunnelService.open_tunnel(entry.tunnel_port, entry.home_port, entry.home_host)
                entry.tunnel_pid = pid
                entry.tunnel_status = ProxyEntry.TUNNEL_OPEN
            except Exception as e:
                entry.tunnel_status = ProxyEntry.TUNNEL_ERROR
                messages.error(request, f'Failed to open tunnel: {e}')
        entry.save()
        return redirect('proxy_entry_detail', pk=entry.pk)
