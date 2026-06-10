import sys
from rest_framework import serializers
from tunnels.models import Home
from tunnels.ssh.manage_home import tunnel_manager


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


class HomeBandwidthSerializer(serializers.Serializer):
    bandwidth_limit_kbps = serializers.IntegerField(
        min_value=100,
        max_value=10_000_000,
        allow_null=True,
    )


class ProxyMappingHttpSerializer(serializers.Serializer):
    host = serializers.CharField(help_text='Hostname to expose (must be under a registered base domain)')


class WebProxyMappingResponseSerializer(serializers.Serializer):
    scheme = serializers.ChoiceField(choices=['http', 'https'])
    host = serializers.CharField()
    tunnel_port = serializers.IntegerField()


class ProxyMappingTcpSerializer(serializers.Serializer):
    public_port = serializers.IntegerField(help_text='Public TCP port to expose (must be in this home\'s TCP port range)')


class TcpProxyMappingResponseSerializer(serializers.Serializer):
    scheme = serializers.ChoiceField(choices=['tcp'])
    public_port = serializers.IntegerField()
    tunnel_port = serializers.IntegerField()


class BaseDomainSerializer(serializers.Serializer):
    domain = serializers.CharField(help_text='e.g. mysite.example.com')


class BaseDomainResponseSerializer(serializers.Serializer):
    domain = serializers.CharField()
    created_at = serializers.DateTimeField()


class OutHomeSerializer(serializers.ModelSerializer):

    ssh_username = serializers.SerializerMethodField()
    port_base = serializers.SerializerMethodField()
    port_count = serializers.SerializerMethodField()
    tcp_port_base = serializers.SerializerMethodField()
    tcp_port_count = serializers.SerializerMethodField()
    base_domains = serializers.SerializerMethodField()

    def get_ssh_username(self, obj: Home) -> str:
        return tunnel_manager.make_username(home_index=obj.home_index, suffix=obj.user.username)

    def get_port_base(self, obj: Home) -> int:
        return tunnel_manager.get_home_port_base(home_id=obj.home_index)

    def get_port_count(self, obj: Home) -> int:
        return tunnel_manager.config.PORTS_PER_HOME

    def get_tcp_port_base(self, obj: Home) -> int:
        return tunnel_manager.get_home_tcp_public_port_base(home_id=obj.home_index)

    def get_tcp_port_count(self, obj: Home) -> int:
        return tunnel_manager.config.TCP_PUBLIC_PORTS_PER_HOME

    def get_base_domains(self, obj: Home) -> list:
        return list(obj.base_domains.values_list('domain', flat=True))

    class Meta:
        model = Home
        fields = ['slug', 'ssh_username', 'port_base', 'port_count', 'tcp_port_base', 'tcp_port_count', 'bandwidth_limit_kbps', 'base_domains']
