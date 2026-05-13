from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator

from homes.tunnels.manage_tunnel import tunnel_manager


class ProxyMapping(models.Model):
    SCHEME_HTTP = 'http'
    SCHEME_HTTPS = 'https'
    SCHEME_CHOICES = [(SCHEME_HTTP, 'HTTP'), (SCHEME_HTTPS, 'HTTPS')]

    home = models.ForeignKey('Home', on_delete=models.CASCADE, related_name='proxy_mappings')
    host = models.CharField(max_length=253, unique=True)
    tunnel_port = models.IntegerField()
    scheme = models.CharField(max_length=5, choices=SCHEME_CHOICES, default=SCHEME_HTTPS)

    def __str__(self):
        return f'{self.host} -> {self.home.get_username}'


class Home(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name='homes')
    home_index = models.IntegerField(primary_key=True, validators=[MinValueValidator(0), MaxValueValidator(9)])
    public_key = models.TextField(max_length=800, blank=True, null=True)
    slug = models.CharField(max_length=32, unique=True, null=True, blank=True)

    def __str__(self):
        return f'Home {self.home_index} - ssh_username: {self.get_username}'

    @property
    def get_username(self):
        return tunnel_manager.make_username(home_index=self.home_index, suffix=self.user.username) if self.user else None
