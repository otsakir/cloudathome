import re

from django import forms
from django.contrib.auth.models import User

from homes.tunnels.manage_tunnel import Config

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
