import requests
from urllib.parse import urlparse

from django.shortcuts import redirect
from django.views.generic import FormView, TemplateView

from cloudlink.models import CloudConfig
from cloudlink.forms import SetupForm
from domains.models import Domain


class SetupWizardView(FormView):
    template_name = 'cloudlink/setup.html'
    form_class = SetupForm

    def dispatch(self, request, *args, **kwargs):
        if CloudConfig.get() is not None:
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        url = form.cleaned_data['cloudserver_url'].rstrip('/')

        try:
            r = requests.post(
                f'{url}/api/auth/authtoken/',
                json={'username': form.cleaned_data['username'], 'password': form.cleaned_data['password']},
                timeout=10,
            )
            r.raise_for_status()
            token = r.json()['token']
        except Exception as e:
            form.add_error(None, f'Authentication failed: {e}')
            return self.form_invalid(form)

        try:
            r = requests.post(
                f'{url}/api/homes/',
                json={'public_key': form.cleaned_data['public_key']},
                headers={'Authorization': f'Token {token}'},
                timeout=10,
            )
            r.raise_for_status()
            home = r.json()
        except Exception as e:
            form.add_error(None, f'Failed to register home with cloudserver: {e}')
            return self.form_invalid(form)

        config = CloudConfig()
        config.cloudserver_url = url
        config.auth_token = token
        config.home_slug = home['slug']
        config.ssh_host = urlparse(url).hostname
        config.ssh_port = form.cleaned_data['ssh_port']
        config.ssh_username = home['ssh_username']
        config.private_key_path = form.cleaned_data['private_key_path']
        config.port_base = home['port_base']
        config.port_count = home['port_count']
        config.save()

        return redirect('dashboard')


class DashboardView(TemplateView):
    template_name = 'cloudlink/dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if CloudConfig.get() is None:
            return redirect('setup')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['config'] = CloudConfig.get()
        context['domains'] = Domain.objects.all()
        return context
