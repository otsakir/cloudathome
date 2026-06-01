from django import forms
from django.shortcuts import render
from django.views.generic import TemplateView, FormView

from playbooks.certificate import IssueCertificatePlaybook


class PlaybookIndexView(TemplateView):
    template_name = 'playbooks/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['playbooks'] = [
            {
                'name': IssueCertificatePlaybook.name,
                'description': IssueCertificatePlaybook.description,
                'url_name': 'playbook_issue_certificate',
            },
        ]
        return context


class IssueCertificateForm(forms.Form):
    domain_name = forms.CharField(
        max_length=253,
        label='Domain name',
        help_text='e.g. mysite.example.com — must be under one of your registered base domains.',
    )
    email = forms.EmailField(
        label='Email',
        help_text="Used by Let's Encrypt for expiry notifications.",
    )
    home_port = forms.IntegerField(
        min_value=1,
        max_value=65535,
        initial=8080,
        label='Local certbot port',
        help_text='Certbot listens on this port during the HTTP-01 challenge. Must not be in use.',
    )


class IssueCertificateView(FormView):
    template_name = 'playbooks/issue_certificate.html'
    form_class = IssueCertificateForm

    def form_valid(self, form):
        result = IssueCertificatePlaybook().run(**form.cleaned_data)
        return render(self.request, 'playbooks/result.html', {
            'playbook_name': IssueCertificatePlaybook.name,
            'result': result,
            'domain_name': form.cleaned_data['domain_name'],
        })
