from django import forms


class AddDomainForm(forms.Form):
    name = forms.CharField(
        max_length=253,
        label='Domain name',
        help_text='e.g. mysite.example.com',
    )
    email = forms.EmailField(
        label='Email address',
        help_text="Used by Let's Encrypt for renewal notifications.",
    )
    cert_output_path = forms.CharField(
        max_length=512,
        label='Certificate output directory',
        help_text='Absolute path on this machine where certificates will be stored.',
    )


class ProxyEntryForm(forms.Form):
    cloudserver_host = forms.CharField(
        max_length=253,
        label='Public hostname',
        help_text='The domain name HAProxy will route to this entry.',
    )
    home_port = forms.IntegerField(
        label='Home port',
        help_text='Port of the local service (e.g. 443 for HTTPS).',
    )
