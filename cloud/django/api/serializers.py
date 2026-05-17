import sys
from rest_framework import serializers
from homes.models import ProxyMapping, Home
from homes.tunnels.manage_tunnel import tunnel_manager


class ProxyMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyMapping
        fields = ['id', 'host', 'tunnel_port', 'scheme']
        read_only_fields = ['id', 'tunnel_port']


class HomeSerializer(serializers.Serializer):
    public_key = serializers.CharField(max_length=800, required=True)

    def update(self, instance: Home, validated_data):
        assert instance.user is None

        instance.public_key = validated_data['public_key']
        instance.user = validated_data.get('user')
        instance.slug = validated_data.get('slug')
        instance.save()



class UpdateHomeKeySerializer(serializers.Serializer):
    public_key = serializers.CharField(max_length=800)


class OutHomeSerializer(serializers.ModelSerializer):

    ssh_username = serializers.SerializerMethodField()
    port_base = serializers.SerializerMethodField()
    port_count = serializers.SerializerMethodField()

    def get_ssh_username(self, obj: Home) -> str:
        return tunnel_manager.make_username(home_index=obj.home_index, suffix=obj.user.username)

    def get_port_base(self, obj: Home) -> int:
        return tunnel_manager.get_home_port_base(home_id=obj.home_index)

    def get_port_count(self, obj: Home) -> int:
        return tunnel_manager.config.PORTS_PER_HOME

    class Meta:
        model = Home
        fields = ['slug', 'ssh_username', 'port_base', 'port_count']
