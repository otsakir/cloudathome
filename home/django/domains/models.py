from django.db import models


class Domain(models.Model):
    CERT_PENDING = 'pending'
    CERT_VALID = 'valid'
    CERT_EXPIRED = 'expired'
    CERT_STATUS_CHOICES = [
        (CERT_PENDING, 'Pending'),
        (CERT_VALID, 'Valid'),
        (CERT_EXPIRED, 'Expired'),
    ]

    name = models.CharField(max_length=253, unique=True)
    cert_status = models.CharField(max_length=10, choices=CERT_STATUS_CHOICES, default=CERT_PENDING)
    cert_expiry = models.DateTimeField(null=True, blank=True)
    cert_path = models.CharField(max_length=512, blank=True)
    deploy_path = models.CharField(max_length=512, blank=True,
                                   help_text='Where to copy issued certificates. Overrides the global certbot.deploy_path. Relative paths are resolved against the config.yaml directory.')

    def __str__(self):
        return self.name


class ProxyEntry(models.Model):
    """
    Holds information about a tunnel including dynamic properties. Tunnel ports (cloud side and home side), entry
    point hostname (cloudserver_host) and scheme (http/https). When the ssh tunnel is in place it also contains the pid
    of the ssh process.

    """
    SCHEME_HTTP = 'http'
    SCHEME_HTTPS = 'https'
    SCHEME_CHOICES = [(SCHEME_HTTP, 'HTTP'), (SCHEME_HTTPS, 'HTTPS')]

    TUNNEL_CLOSED = 'closed'
    TUNNEL_OPEN = 'open'
    TUNNEL_ERROR = 'error'
    TUNNEL_STATUS_CHOICES = [
        (TUNNEL_CLOSED, 'Closed'),
        (TUNNEL_OPEN, 'Open'),
        (TUNNEL_ERROR, 'Error'),
    ]

    domain = models.OneToOneField(Domain, on_delete=models.CASCADE, related_name='proxy_entry')
    cloudserver_host = models.CharField(max_length=253, unique=True)
    tunnel_port = models.IntegerField()
    home_port = models.IntegerField()
    scheme = models.CharField(max_length=5, choices=SCHEME_CHOICES, default=SCHEME_HTTPS)
    tunnel_pid = models.IntegerField(null=True, blank=True)
    tunnel_status = models.CharField(max_length=6, choices=TUNNEL_STATUS_CHOICES, default=TUNNEL_CLOSED)

    def __str__(self):
        return f'{self.cloudserver_host} → :{self.home_port} ({self.scheme})'
