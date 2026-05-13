from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView, DetailView, FormView

from cloudlink.services import CloudServerClient, CloudServerError
from domains.forms import AddDomainForm, ProxyEntryForm
from domains.models import Domain, ProxyEntry
from domains.services import DomainOrchestrator, OrchestratorError, TunnelService


class DomainListView(ListView):
    model = Domain
    template_name = 'domains/domain_list.html'
    context_object_name = 'domains'


class AddDomainView(FormView):
    template_name = 'domains/add_domain.html'
    form_class = AddDomainForm

    def form_valid(self, form):
        try:
            domain = DomainOrchestrator.add_domain(
                name=form.cleaned_data['name'],
                email=form.cleaned_data['email'],
                cert_output_path=form.cleaned_data['cert_output_path'],
            )
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
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
        client = CloudServerClient()
        for entry in domain.proxy_entries.all():
            if entry.tunnel_pid:
                try:
                    TunnelService.close_tunnel(entry.tunnel_pid)
                except Exception:
                    pass
            try:
                client.delete_proxy_mapping(entry.cloudserver_host)
            except Exception:
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
        context = super().get_context_data(**kwargs)
        context['domain'] = self.domain
        return context

    def form_valid(self, form):
        try:
            tunnel_port = DomainOrchestrator.allocate_tunnel_port()
        except OrchestratorError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        client = CloudServerClient()
        try:
            client.create_proxy_mapping(
                form.cleaned_data['cloudserver_host'], tunnel_port, 'https'
            )
        except CloudServerError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        ProxyEntry.objects.create(
            domain=self.domain,
            cloudserver_host=form.cleaned_data['cloudserver_host'],
            tunnel_port=tunnel_port,
            home_port=form.cleaned_data['home_port'],
            scheme=ProxyEntry.SCHEME_HTTPS,
        )
        return redirect('domain_detail', pk=self.domain.pk)


class TunnelToggleView(View):
    def post(self, request, pk):
        entry = get_object_or_404(ProxyEntry, pk=pk)
        if entry.tunnel_status == ProxyEntry.TUNNEL_OPEN:
            if entry.tunnel_pid:
                try:
                    TunnelService.close_tunnel(entry.tunnel_pid)
                except Exception:
                    pass
            entry.tunnel_pid = None
            entry.tunnel_status = ProxyEntry.TUNNEL_CLOSED
        else:
            try:
                pid = TunnelService.open_tunnel(entry.tunnel_port, entry.home_port)
                entry.tunnel_pid = pid
                entry.tunnel_status = ProxyEntry.TUNNEL_OPEN
            except Exception:
                entry.tunnel_status = ProxyEntry.TUNNEL_ERROR
        entry.save()
        return redirect('domain_detail', pk=entry.domain_id)
