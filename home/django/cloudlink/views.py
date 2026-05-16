from django.views.generic import TemplateView

from cloudlink.config import get_config
from domains.models import Domain


class DashboardView(TemplateView):
    template_name = 'cloudlink/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['config'] = get_config()
        context['domains'] = Domain.objects.all()
        return context
