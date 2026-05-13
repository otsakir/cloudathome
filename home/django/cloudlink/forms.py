from django import forms


class SetupForm(forms.Form):
    cloudserver_url = forms.URLField(label='CloudServer URL', help_text='e.g. https://cloudserver.example.com')
    username = forms.CharField(max_length=150, label='Username')
    password = forms.CharField(widget=forms.PasswordInput, label='Password')
    public_key = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4}),
        label='SSH public key',
        max_length=800,
        help_text='Contents of the SSH public key to register with the cloudserver.',
    )
    private_key_path = forms.CharField(
        max_length=512,
        label='SSH private key path',
        help_text='Absolute path to the matching private key on this machine.',
    )
    ssh_port = forms.IntegerField(
        label='SSH port',
        initial=22,
        help_text='SSH port on the cloudserver.',
    )
