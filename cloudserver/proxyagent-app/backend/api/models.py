from django.db import models


class ProxyMapping(models.Model):
    port = models.IntegerField()

