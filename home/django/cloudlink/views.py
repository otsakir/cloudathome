from django import forms
from django.urls import reverse_lazy
from django.views.generic import TemplateView, FormView

from cloudlink.config import get_config
from cloudlink.services import CloudServerClient, CloudServerError
from domains.models import Domain


class DashboardView(TemplateView):
    template_name = 'cloudlink/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['config'] = get_config()
        context['domains'] = Domain.objects.all()
        try:
            home = CloudServerClient().get_home()
            context['bandwidth_limit_kbps'] = home.get('bandwidth_limit_kbps')
        except Exception:
            context['bandwidth_limit_kbps'] = None
        return context


class SetBandwidthForm(forms.Form):
    bandwidth_limit_kbps = forms.IntegerField(
        min_value=100,
        max_value=10_000_000,
        required=False,
        label='Bandwidth limit (kbps)',
        help_text='Leave empty to remove the limit. Example: 5000 = 5 Mbps.',
    )


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
