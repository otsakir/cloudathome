from django.db import models
from autoslug import AutoSlugField
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator


class ProxyMapping(models.Model):
    port = models.IntegerField(unique=True)
    slug = AutoSlugField(populate_from='name', unique=True)
    name = models.CharField(max_length=50)


class Home(models.Model):
    name = models.CharField(max_length=30, blank=True, null=True)
    home_index = models.IntegerField(primary_key=True, validators=[MinValueValidator(0), MaxValueValidator(9)])
    public_key = models.TextField(max_length=800, blank=True, null=True)
    assigned = models.BooleanField(default=False)

    def __str__(self):
        return f'Home {self.home_index}: name:{self.name}, assigned: {self.assigned}'

