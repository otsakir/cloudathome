from rest_framework import serializers
from .models import ProxyMapping


class ProxyMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyMapping
        fields = ['id', 'name', 'slug', 'port']

