from django.db import models


class CloudConfig(models.Model):
    cloudserver_url = models.URLField()
    auth_token = models.CharField(max_length=64, blank=True)
    home_slug = models.SlugField(blank=True)
    ssh_host = models.CharField(max_length=253, blank=True)
    ssh_port = models.IntegerField(default=22)
    ssh_username = models.CharField(max_length=64, blank=True)
    private_key_path = models.CharField(max_length=512, blank=True)
    port_base = models.IntegerField(default=2000)
    port_count = models.IntegerField(default=10)

    @classmethod
    def get(cls):
        return cls.objects.first()

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
