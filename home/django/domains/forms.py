from django import forms

from domains.models import ProxyEntry


class AddDomainForm(forms.Form):
    name = forms.CharField(
        max_length=253,
        label='Domain name',
        help_text='e.g. mysite.example.com',
    )

    def __init__(self, *args, base_domains=None, **kwargs):
        """base_domains: list of registered base domains, or None if they
        couldn't be fetched (in which case validation is skipped -- the
        cloud will still enforce this when a proxy mapping is created)."""
        super().__init__(*args, **kwargs)
        self.base_domains = base_domains

    def clean_name(self):
        name = self.cleaned_data['name'].strip().lower()
        if self.base_domains is not None:
            if not self.base_domains:
                raise forms.ValidationError(
                    'You have no registered base domains yet. Register one from the dashboard first.'
                )
            if not any(name == bd or name.endswith('.' + bd) for bd in self.base_domains):
                raise forms.ValidationError(
                    f"'{name}' must be equal to or a subdomain of one of your registered base "
                    f"domains: {', '.join(self.base_domains)}"
                )
        return name


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
