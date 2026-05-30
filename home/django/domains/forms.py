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
    home_host = forms.CharField(
        max_length=253,
        initial='localhost',
        required=False,
        label='Home network host',
        help_text='Hostname or IP of the target service on the home network.',
    )
    home_port = forms.IntegerField(
        label='Home port',
        help_text='Port of the local service (e.g. 443 for HTTPS).',
    )


class TcpProxyEntryForm(forms.Form):
    public_port = forms.IntegerField(
        label='Public port',
        help_text='Port on the cloud server clients will connect to (must be within your allocated TCP range).',
    )
    home_host = forms.CharField(
        max_length=253,
        initial='localhost',
        required=False,
        label='Home network host',
        help_text='Hostname or IP of the target service on the home network.',
    )
    home_port = forms.IntegerField(
        label='Home port',
        help_text='Port of the local service to expose.',
    )


class IssueCertificateForm(forms.Form):
    email = forms.EmailField(
        label='Email address',
        help_text="Used by Let's Encrypt for renewal notifications.",
    )
