import sys
from rest_framework import serializers
from .models import ProxyMapping, Home
from django.core.validators import RegexValidator


class ProxyMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyMapping
        fields = ['id', 'name', 'slug', 'port']


class HomeSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=30, validators=[RegexValidator(regex='^[a-z0-9_-]{1,20}$')]) # TODO use same regex pattern as the one in manage_tunnel.py
    public_key = serializers.CharField(max_length=800, required=True)

    def update(self, instance: Home, validated_data):
        assert not instance.assigned

        print("updating unassigned home", instance.home_index, ' with data', validated_data, file=sys.stderr)
        instance.name = validated_data['name']
        instance.public_key = validated_data['public_key']
        instance.assigned = True

        instance.save()

        # fields = ['name', 'public_key']



