import re

from django import forms
from django.contrib.auth.models import User

from tunnels.services import HAProxyService
from tunnels.ssh.manage_home import Config, tunnel_manager

_USERNAME_PATTERN = re.compile(f'^{Config.USERNAME_SUFFIX_PATTERN}$')


class SignupForm(forms.Form):
    full_name = forms.CharField(max_length=150, label='Full name')
    username = forms.CharField(max_length=20, label='Username')
    email = forms.EmailField(label='Contact email')
    password = forms.CharField(widget=forms.PasswordInput, label='Password')
    password_confirm = forms.CharField(widget=forms.PasswordInput, label='Confirm password')

    def clean_username(self):
        username = self.cleaned_data['username']
        if not _USERNAME_PATTERN.match(username):
            raise forms.ValidationError(
                'Username must be 1–20 characters and contain only lowercase letters, digits, hyphens, or underscores.'
            )
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('That username is already taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password') != cleaned.get('password_confirm'):
            self.add_error('password_confirm', 'Passwords do not match.')
        return cleaned


class UpdatePublicKeyForm(forms.Form):
    public_key = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4}),
        label='SSH public key',
        max_length=800,
    )


class RegisterHomeForm(UpdatePublicKeyForm):
    private_key_path = forms.CharField(
        required=False,
        max_length=500,
        label='Local private key path',
        help_text=(
            'Path to the matching private key on your home machine (from generate_keys.py). '
            'Only used to pre-fill the generated config.yaml below — not stored on the server.'
        ),
    )


_SCHEME_CHOICES = [('http', 'HTTP'), ('https', 'HTTPS')]


class AddMappingForm(forms.Form):
    host = forms.CharField(max_length=253, label='Hostname')
    tunnel_port = forms.IntegerField(label='Tunnel port')
    scheme = forms.ChoiceField(choices=_SCHEME_CHOICES, label='Scheme')

    def __init__(self, *args, home=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.home = home

    def clean_host(self):
        host = self.cleaned_data['host']
        used_hosts = {e['host'] for e in HAProxyService.dump_mappings()}
        if host in used_hosts:
            raise forms.ValidationError('A mapping for this hostname already exists.')
        return host

    def clean_tunnel_port(self):
        port = self.cleaned_data['tunnel_port']
        if self.home:
            port_base = tunnel_manager.get_home_port_base(self.home.home_index)
            port_max = port_base + tunnel_manager.config.PORTS_PER_HOME - 1
            if not (port_base <= port <= port_max):
                raise forms.ValidationError(
                    f'Port must be between {port_base} and {port_max} for your home slot.'
                )
            if port in HAProxyService.get_used_ports():
                raise forms.ValidationError('That tunnel port is already in use.')
        return port
