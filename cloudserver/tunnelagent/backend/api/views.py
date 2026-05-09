import sys
import secrets

from rest_framework.generics import ListAPIView, CreateAPIView, ListCreateAPIView, RetrieveDestroyAPIView
from rest_framework.views import APIView
from homes.models import ProxyMapping, Home
from .serializers import ProxyMappingSerializer, HomeSerializer, OutHomeSerializer
# from haproxyadmin.haproxy import HAProxy
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status
from homes.services import ElevatedOperations
from homes.services import HAProxyService
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from drf_spectacular.utils import extend_schema, OpenApiResponse



class HomeRetrieveDestroyApiView(RetrieveDestroyAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = OutHomeSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Home.objects.filter(user=self.request.user)

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
    authentication_classes = [SessionAuthentication]
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


class ProxyMappingListCreateView(ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ProxyMappingSerializer

    def get_home(self):
        return get_object_or_404(Home, slug=self.kwargs['home_slug'], user=self.request.user)

    def get_queryset(self):
        return ProxyMapping.objects.filter(home=self.get_home())

    def create(self, request, *args, **kwargs):
        home = self.get_home()
        serializer = ProxyMappingSerializer(data=request.data, context={'home': home})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        mapping = serializer.save(home=home)

        try:
            HAProxyService.add_mapping(mapping)
        except Exception:
            mapping.delete()
            return Response({'message': 'failed to configure proxy'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ProxyMappingDestroyAPIView(RetrieveDestroyAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ProxyMappingSerializer
    lookup_field = 'host'

    def get_queryset(self):
        return ProxyMapping.objects.filter(
            home__slug=self.kwargs['home_slug'],
            home__user=self.request.user,
        )

    def destroy(self, request, *args, **kwargs):
        mapping = self.get_object()

        try:
            HAProxyService.remove_mapping(mapping)
        except Exception:
            return Response({'message': 'failed to remove proxy mapping'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        mapping.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProxyInstanceAPIView(APIView):
    def get(self, request):
        print('in ProxyInstance GET')
        pass


class ProxyMappingSyncView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request):
        mappings = list(ProxyMapping.objects.select_related('home').all())
        try:
            HAProxyService.sync_mappings(mappings)
        except Exception:
            return Response({'message': 'failed to sync proxy mappings'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'synced': len(mappings)})


class ProxyMappingDumpView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            entries = HAProxyService.dump_mappings()
        except Exception:
            return Response({'message': 'failed to read proxy mappings from haproxy'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(entries)


class HomeSyncView(APIView):
    authentication_classes = [SessionAuthentication]
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
