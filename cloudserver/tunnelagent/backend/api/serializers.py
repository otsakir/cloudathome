import sys
from rest_framework import serializers
from .models import ProxyMapping, Home
from django.core.validators import RegexValidator
from external.tunnels.manage_tunnel import tunnel_manager


class ProxyMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyMapping
        fields = ['id', 'name', 'slug', 'port']


class HomeSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=30, required=False, validators=[RegexValidator(regex='^[a-z0-9_-]{1,20}$')]) # TODO use same regex pattern as the one in manage_tunnel.py
    public_key = serializers.CharField(max_length=800, required=True)

    def update(self, instance: Home, validated_data):
        assert not instance.assigned

        print("updating unassigned home", instance.home_index, ' with data', validated_data, file=sys.stderr)
        instance.name = validated_data['name']
        instance.public_key = validated_data['public_key']
        instance.assigned = True

        instance.save()


class CreateHomeSerializer(serializers.Serializer):
    public_key = serializers.CharField(max_length=800)


class OutHomeSerializer(serializers.ModelSerializer):

    ssh_username = serializers.SerializerMethodField()
    port_base = serializers.SerializerMethodField()
    port_count = serializers.SerializerMethodField()

    def get_ssh_username(self, obj: Home):
        ssh_username = tunnel_manager.make_username(home_index=obj.home_index, suffix=obj.name)
        return ssh_username

    def get_port_base(self, obj: Home):
        port_base = tunnel_manager.get_home_port_base(home_id=obj.home_index)
        return port_base

    def get_port_count(self, obj: Home):
        return tunnel_manager.config.PORTS_PER_HOME

    class Meta:
        model = Home
        fields = ['name', 'ssh_username', 'port_base', 'port_count']



