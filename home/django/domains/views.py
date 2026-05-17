from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView, DetailView, FormView

from cloudlink.services import CloudServerClient, CloudServerError
from domains.forms import AddDomainForm, ProxyEntryForm
from domains.models import Domain, ProxyEntry
from domains.services import TunnelService


class DomainListView(ListView):
    model = Domain
    template_name = 'domains/domain_list.html'
    context_object_name = 'domains'


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
        client = CloudServerClient()
        try:
            entry = domain.proxy_entry
            if entry.tunnel_pid:
                try:
                    TunnelService.close_tunnel(entry.tunnel_pid)
                except Exception:
                    pass
            try:
                client.delete_proxy_mapping(entry.cloudserver_host)
            except Exception:
                pass
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
        context = super().get_context_data(**kwargs)
        context['domain'] = self.domain
        return context

    def form_valid(self, form):
        client = CloudServerClient()
        try:
            result = client.create_proxy_mapping(self.domain.name, form.cleaned_data['scheme'])
        except CloudServerError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        entry = ProxyEntry.objects.create(
            domain=self.domain,
            cloudserver_host=self.domain.name,
            tunnel_port=result['tunnel_port'],
            home_port=form.cleaned_data['home_port'],
            scheme=form.cleaned_data['scheme'],
        )
        return redirect('proxy_entry_detail', pk=entry.pk)


class ProxyEntryDetailView(DetailView):
    model = ProxyEntry
    template_name = 'domains/proxy_entry_detail.html'


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
        return redirect('proxy_entry_detail', pk=entry.pk)
