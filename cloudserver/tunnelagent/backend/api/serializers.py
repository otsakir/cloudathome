import sys
from rest_framework import serializers
from .models import ProxyMapping, Home
from external.tunnels.manage_tunnel import tunnel_manager


class ProxyMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyMapping
        fields = ['id', 'slug', 'host', 'local_port', 'scheme']
        read_only_fields = ['id', 'slug']

    def validate_scheme(self, value):
        if value != ProxyMapping.SCHEME_HTTPS:
            raise serializers.ValidationError('Only https is supported.')
        return value

    def validate(self, data):
        home = self.context['home']
        local_port = data['local_port']
        port_base = tunnel_manager.get_home_port_base(home.home_index)
        port_max = port_base + tunnel_manager.config.PORTS_PER_HOME - 1
        if not (port_base <= local_port <= port_max):
            raise serializers.ValidationError({
                'local_port': f'Must be in range {port_base}–{port_max} for home {home.home_index}.'
            })
        return data


class HomeSerializer(serializers.Serializer):
    public_key = serializers.CharField(max_length=800, required=True)

    def update(self, instance: Home, validated_data):
        assert instance.user is None

        instance.public_key = validated_data['public_key']
        instance.user = validated_data.get('user')
        instance.slug = validated_data.get('slug')
        instance.save()



class OutHomeSerializer(serializers.ModelSerializer):

    ssh_username = serializers.SerializerMethodField()
    port_base = serializers.SerializerMethodField()
    port_count = serializers.SerializerMethodField()

    def get_ssh_username(self, obj: Home):
        return tunnel_manager.make_username(home_index=obj.home_index, suffix=obj.user.username)

    def get_port_base(self, obj: Home):
        port_base = tunnel_manager.get_home_port_base(home_id=obj.home_index)
        return port_base

    def get_port_count(self, obj: Home):
        return tunnel_manager.config.PORTS_PER_HOME

    class Meta:
        model = Home
        fields = ['slug', 'ssh_username', 'port_base', 'port_count']
