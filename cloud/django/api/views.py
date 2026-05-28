import sys
import secrets

from rest_framework.generics import RetrieveDestroyAPIView, ListCreateAPIView
from rest_framework.views import APIView
from homes.models import Home
from .serializers import HomeSerializer, OutHomeSerializer, UpdateHomeKeySerializer, HomeBandwidthSerializer
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework import status
from homes.services import ElevatedOperations
from homes.services import HAProxyService
from homes.tunnels.manage_home import tunnel_manager
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from drf_spectacular.utils import extend_schema, OpenApiResponse



class HomeRetrieveDestroyApiView(RetrieveDestroyAPIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = OutHomeSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Home.objects.filter(user=self.request.user)

    @extend_schema(request=UpdateHomeKeySerializer, responses={200: OutHomeSerializer})
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


class HomeListCreateAPIView(ListCreateAPIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = OutHomeSerializer

    def get_queryset(self):
        return Home.objects.filter(user=self.request.user)

    @extend_schema(
        request=HomeSerializer,
        responses={
            201: OutHomeSerializer,
            409: OpenApiResponse(description='No available home slots'),
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


class ProxyMappingListCreateView(APIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def _get_home(self, home_slug, user):
        return get_object_or_404(Home, slug=home_slug, user=user)

    def get(self, request, home_slug):
        home = self._get_home(home_slug, request.user)
        port_base = tunnel_manager.get_home_port_base(home.home_index)
        mappings = HAProxyService.get_home_mappings(port_base, tunnel_manager.config.PORTS_PER_HOME)
        return Response(mappings)

    def post(self, request, home_slug):
        home = self._get_home(home_slug, request.user)
        host = request.data.get('host')
        scheme = request.data.get('scheme')
        if not host or scheme not in ('http', 'https'):
            return Response({'message': 'host and scheme (http or https) are required'}, status=status.HTTP_400_BAD_REQUEST)

        port_base = tunnel_manager.get_home_port_base(home.home_index)
        port_max = port_base + tunnel_manager.config.PORTS_PER_HOME
        used = HAProxyService.get_used_ports()
        try:
            tunnel_port = next(p for p in range(port_base, port_max) if p not in used)
        except StopIteration:
            return Response({'message': 'no free tunnel ports available'}, status=status.HTTP_409_CONFLICT)

        try:
            HAProxyService.add_mapping(host, tunnel_port, scheme)
        except Exception:
            return Response({'message': 'failed to configure proxy'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'host': host, 'tunnel_port': tunnel_port, 'scheme': scheme}, status=status.HTTP_201_CREATED)


class ProxyMappingDestroyAPIView(APIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, home_slug, host):
        get_object_or_404(Home, slug=home_slug, user=request.user)
        try:
            HAProxyService.remove_mapping(host)
        except Exception:
            return Response({'message': 'failed to remove proxy mapping'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(exclude=True)
class ProxyInstanceAPIView(APIView):
    def get(self, request):
        pass


class ProxyMappingDumpView(APIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            entries = HAProxyService.dump_mappings()
        except Exception:
            return Response({'message': 'failed to read proxy mappings from haproxy'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(entries)


class HomeSyncView(APIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
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
