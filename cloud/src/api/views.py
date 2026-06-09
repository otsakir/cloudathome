import sys
import secrets

from rest_framework.generics import RetrieveDestroyAPIView, ListCreateAPIView, CreateAPIView, ListAPIView
from rest_framework.views import APIView
from homes.models import Home
from .serializers import HomeSerializer, OutHomeSerializer, UpdateHomeKeySerializer, HomeBandwidthSerializer, ProxyMappingHttpSerializer, ProxyMappingTcpSerializer, WebProxyMappingResponseSerializer, TcpProxyMappingResponseSerializer, BaseDomainSerializer, BaseDomainResponseSerializer

from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework import status
from homes.models import HomeBaseDomain
from homes.services import ElevatedOperations, HAProxyService, BaseDomainService
from homes.tunnels.manage_home import tunnel_manager
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, inline_serializer
from rest_framework import serializers as drf_serializers



@extend_schema_view(
    get=extend_schema(
        tags=['homes'],
        summary='Get home details',
        description='Returns connection details for the specified home: SSH username, tunnel port range, TCP public port range, bandwidth limit, and registered base domains.',
        responses={200: OutHomeSerializer},
    ),
    delete=extend_schema(
        summary='Release home slot',
        description='Removes the SSH tunnel user and releases the home slot, making it available for other users. All active tunnels and HAProxy mappings must be removed by the home before calling this.',
        responses={
            204: OpenApiResponse(description='Home released'),
            500: OpenApiResponse(description='Failed to remove tunnel user'),
        },
    )
)
class HomeRetrieveDestroyApiView(RetrieveDestroyAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = OutHomeSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Home.objects.filter(user=self.request.user)

    @extend_schema(
        tags=['homes'],
        summary='Update home',
        description=(
            'Updates the SSH public key and/or bandwidth limit for the home. '
            'Pass `public_key` to rotate the tunnel key, `bandwidth_limit_kbps` to set an egress rate limit (set to null to remove it).'
        ),
        request=UpdateHomeKeySerializer,
        responses={
            200: OutHomeSerializer,
            400: OpenApiResponse(description='Invalid field value'),
            500: OpenApiResponse(description='Failed to apply changes'),
        },
    )
    def patch(self, request, *args, **kwargs):
        home = self.get_object()

        if 'public_key' in request.data:
            s = UpdateHomeKeySerializer(data=request.data)
            if not s.is_valid():
                return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
            try:
                ElevatedOperations.update_home_user_key(
                    home.home_index,
                    home.user.username,
                    s.validated_data['public_key'],
                )
            except Exception:
                return Response({'message': 'failed to update public key'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            home.public_key = s.validated_data['public_key']
            home.save()

        if 'bandwidth_limit_kbps' in request.data:
            s = HomeBandwidthSerializer(data=request.data)
            if not s.is_valid():
                return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
            new_limit = s.validated_data['bandwidth_limit_kbps']
            try:
                if new_limit:
                    ElevatedOperations.set_home_bandwidth(home.home_index, new_limit)
                else:
                    ElevatedOperations.unset_home_bandwidth(home.home_index)
            except Exception:
                return Response({'message': 'failed to update bandwidth limit'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            home.bandwidth_limit_kbps = new_limit
            home.save()

        return Response(OutHomeSerializer(home).data)


    def destroy(self, request, *args, **kwargs):
        home = self.get_object()

        try:
            ElevatedOperations.remove_home_user(home.home_index, home.user.username)
        except Exception:
            return Response({'message': 'failed to remove tunnel user'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        home.public_key = None
        home.user = None
        home.slug = None
        home.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(
        tags=['homes'],
        summary='List assigned homes',
        description='Returns the home slot assigned to the authenticated user. Currently, a user can hold at most one home at a time.',
        responses={200: OutHomeSerializer(many=True)},
    ),
)
class HomeListCreateAPIView(ListCreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = OutHomeSerializer

    def get_queryset(self):
        return Home.objects.filter(user=self.request.user)

    @extend_schema(
        tags=['homes'],
        summary='Claim a home slot',
        description=(
            'Claims an available home slot and registers the provided SSH public key. '
            'Returns connection details: SSH username, assigned tunnel port range, TCP public port range, and a unique slug for subsequent API calls. '
            'Each user may hold at most one home slot.'
        ),
        request=HomeSerializer,
        responses={
            201: OutHomeSerializer,
            409: OpenApiResponse(description='No available home slots, or user already has a home'),
            500: OpenApiResponse(description='Failed to create tunnel user'),
        },
    )
    def post(self, request):
        s = HomeSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)

        if Home.objects.filter(user=request.user).exists():
            return Response({'message': 'user already has a home'}, status=status.HTTP_409_CONFLICT)

        available_home = Home.objects.filter(user__isnull=True).first()
        if not available_home:
            return Response({'message': 'no available home slots'}, status=status.HTTP_409_CONFLICT)

        try:
            ElevatedOperations.add_home_user(available_home.home_index, request.user.username, s.validated_data['public_key'])
        except Exception:
            return Response({'message': 'failed to create tunnel user'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        HomeSerializer().update(available_home, {**s.validated_data, 'user': request.user, 'slug': secrets.token_urlsafe(16)})

        return Response(OutHomeSerializer(available_home).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=['home proxy mappings'])
)
class ProxyMappingListView(ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def list(self, request, home_slug):
        home = get_object_or_404(Home, slug=home_slug, user=request.user)
        port_base = tunnel_manager.get_home_port_base(home.home_index)
        tcp_port_base = tunnel_manager.get_home_tcp_public_port_base(home.home_index)
        mappings = HAProxyService.get_home_mappings(
            port_base,
            tunnel_manager.config.PORTS_PER_HOME,
            tcp_public_port_base=tcp_port_base,
            tcp_public_port_count=tunnel_manager.config.TCP_PUBLIC_PORTS_PER_HOME,
        )
        return Response(mappings)


@extend_schema_view(
    post=extend_schema(
        tags=['home proxy mappings'],
        responses={201: WebProxyMappingResponseSerializer}
    )
)
class WebProxyMappingCreateView(CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ProxyMappingHttpSerializer

    def create(self, request, home_slug):
        home = get_object_or_404(Home, slug=home_slug, user=request.user)
        s = self.get_serializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        host = s.validated_data['host']
        scheme = s.validated_data['scheme']

        if not BaseDomainService.is_authorized(home, host):
            return Response({'message': 'host is not under any of your registered base domains'}, status=status.HTTP_403_FORBIDDEN)

        port_base = tunnel_manager.get_home_port_base(home.home_index)
        port_max = port_base + tunnel_manager.config.PORTS_PER_HOME
        used = HAProxyService.get_used_ports()
        try:
            tunnel_port = next(p for p in range(port_base, port_max) if p not in used)
        except StopIteration:
            return Response({'message': 'no free tunnel ports available'}, status=status.HTTP_409_CONFLICT)

        try:
            HAProxyService.add_mapping(scheme, tunnel_port, host=host)
        except Exception:
            return Response({'message': 'failed to configure proxy'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'host': host, 'tunnel_port': tunnel_port, 'scheme': scheme}, status=status.HTTP_201_CREATED)


@extend_schema_view(
    post=extend_schema(
        tags=['home proxy mappings'],
        responses={201: TcpProxyMappingResponseSerializer}
    )
)
class TcpProxyMappingCreateView(CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ProxyMappingTcpSerializer

    def create(self, request, home_slug):
        home = get_object_or_404(Home, slug=home_slug, user=request.user)
        s = self.get_serializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        public_port = s.validated_data['public_port']

        port_base = tunnel_manager.get_home_port_base(home.home_index)
        port_max = port_base + tunnel_manager.config.PORTS_PER_HOME

        tcp_port_base = tunnel_manager.get_home_tcp_public_port_base(home.home_index)
        tcp_port_max = tcp_port_base + tunnel_manager.config.TCP_PUBLIC_PORTS_PER_HOME
        if not (tcp_port_base <= public_port < tcp_port_max):
            return Response(
                {'message': f'public_port must be in range {tcp_port_base}–{tcp_port_max - 1} for this home'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if public_port in HAProxyService.get_used_tcp_public_ports():
            return Response({'message': 'public_port already in use'}, status=status.HTTP_409_CONFLICT)

        used = HAProxyService.get_used_ports()
        try:
            tunnel_port = next(p for p in range(port_base, port_max) if p not in used)
        except StopIteration:
            return Response({'message': 'no free tunnel ports available'}, status=status.HTTP_409_CONFLICT)

        try:
            HAProxyService.add_mapping('tcp', tunnel_port, public_port=public_port)
        except Exception:
            return Response({'message': 'failed to configure proxy'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'public_port': public_port, 'tunnel_port': tunnel_port, 'scheme': 'tcp'}, status=status.HTTP_201_CREATED)


@extend_schema(tags=['home proxy mappings'])
class ProxyMappingDestroyAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, home_slug, key):
        get_object_or_404(Home, slug=home_slug, user=request.user)
        try:
            HAProxyService.remove_mapping(key)
        except Exception:
            return Response({'message': 'failed to remove proxy mapping'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(exclude=True)
class ProxyInstanceAPIView(APIView):
    def get(self, request):
        pass


class ProxyMappingDumpView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            entries = HAProxyService.dump_mappings()
        except Exception:
            return Response({'message': 'failed to read proxy mappings from haproxy'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(entries)



@extend_schema_view(
    get=extend_schema(
        tags=['home base domains'],
        summary='List base domains',
        description='Returns all base domains registered for this home. Only hostnames under these domains may be used when creating HTTP/HTTPS proxy mappings.',
        responses={200: BaseDomainResponseSerializer(many=True)},
    ),
    post=extend_schema(
        tags=['home base domains'],
        summary='Register a base domain',
        description=(
            'Registers a base domain for this home. Once registered, proxy mappings can be created for any hostname under this domain. '
            'The domain must be registrable (not a bare TLD or public suffix) and must not overlap with a domain already claimed by another home.'
        ),
        request=BaseDomainSerializer,
        responses={
            201: BaseDomainResponseSerializer,
            409: OpenApiResponse(description='Domain already claimed or overlaps with another home'),
        },
    )
)
class BaseDomainListCreateView(ListCreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = BaseDomainResponseSerializer

    def get_queryset(self):
        home = get_object_or_404(Home, slug=self.kwargs['home_slug'], user=self.request.user)
        return home.base_domains.order_by('domain')

    def create(self, request, *args, **kwargs):
        home = get_object_or_404(Home, slug=self.kwargs['home_slug'], user=request.user)
        s = BaseDomainSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            domain = BaseDomainService.validate(s.validated_data['domain'])
        except ValueError as e:
            return Response({'message': str(e)}, status=status.HTTP_409_CONFLICT)
        bd = HomeBaseDomain.objects.create(home=home, domain=domain)
        return Response(BaseDomainResponseSerializer(bd).data, status=status.HTTP_201_CREATED)



class BaseDomainDestroyView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['home base domains'],
        summary='Remove a base domain',
        description='Removes a registered base domain. All proxy mappings under this domain must be deleted before it can be removed.',
        responses={
            204: OpenApiResponse(description='Domain removed'),
            409: OpenApiResponse(description='Active proxy mappings exist under this domain'),
        },
    )
    def delete(self, request, home_slug, domain):
        home = get_object_or_404(Home, slug=home_slug, user=request.user)
        bd = get_object_or_404(HomeBaseDomain, home=home, domain=domain.lower())
        if BaseDomainService.has_active_mappings(home, domain):
            return Response(
                {'message': 'remove all proxy mappings under this domain before deleting it'},
                status=status.HTTP_409_CONFLICT,
            )
        bd.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class HomeSyncView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request):
        import pwd
        from homes.services import ElevatedOperations as EO

        homes = list(Home.objects.filter(user__isnull=False).select_related('user'))
        reconciled = 0
        for home in homes:
            try:
                pwd.getpwnam(home.get_username)
            except KeyError:
                try:
                    EO.add_home_user(home.home_index, home.user.username, home.public_key)
                    reconciled += 1
                except Exception:
                    return Response(
                        {'message': f'failed to recreate user for home {home.home_index}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        return Response({'reconciled': reconciled})
