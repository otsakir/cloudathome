from django import forms

from domains.models import ProxyEntry


class AddDomainForm(forms.Form):
    name = forms.CharField(
        max_length=253,
        label='Domain name',
        help_text='e.g. mysite.example.com',
    )


class ProxyEntryForm(forms.Form):
    scheme = forms.ChoiceField(
        choices=ProxyEntry.SCHEME_CHOICES,
        label='Scheme',
    )
    home_port = forms.IntegerField(
        label='Home port',
        help_text='Port of the local service (e.g. 443 for HTTPS).',
    )


class IssueCertificateForm(forms.Form):
    email = forms.EmailField(
        label='Email address',
        help_text="Used by Let's Encrypt for renewal notifications.",
    )
