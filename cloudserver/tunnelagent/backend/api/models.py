from django.db import models
from autoslug import AutoSlugField


class ProxyMapping(models.Model):
    port = models.IntegerField(unique=True)
    slug = AutoSlugField(populate_from='name', unique=True)
    name = models.CharField(max_length=50)
