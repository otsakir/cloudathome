import sys

from rest_framework.generics import ListAPIView, CreateAPIView, ListCreateAPIView, RetrieveDestroyAPIView
from rest_framework.views import APIView
from .models import ProxyMapping, Home
from .serializers import ProxyMappingSerializer, HomeSerializer, OutHomeSerializer, CreateHomeSerializer
# from haproxyadmin.haproxy import HAProxy
from django.http import HttpRequest
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status
from external.services import ElevatedOperations
from external.haproxy import HAProxyService
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse



class HomeRetrieveDestroyApiView(RetrieveDestroyAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = OutHomeSerializer

    def get_queryset(self):
        return Home.objects.filter(user=self.request.user)

    def destroy(self, request, pk, *args, **kwargs):
        home = self.get_object()

        if home.user is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            ElevatedOperations.remove_home_user(home.home_index, home.user.username)
        except Exception:
            return Response({'message': 'failed to remove tunnel user'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        home.public_key = None
        home.user = None
        home.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


class HomeListCreateAPIView(ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = OutHomeSerializer

    def get_queryset(self):
        return Home.objects.filter(user=self.request.user)

    @extend_schema(
        request=CreateHomeSerializer,
        responses={
            201: OutHomeSerializer,
            409: OpenApiResponse(description='No available home slots'),
            500: OpenApiResponse(description='Failed to create tunnel user'),
        },
    )
    def post(self, request):
        s = CreateHomeSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)

        available_home = Home.objects.filter(user__isnull=True).first()
        if not available_home:
            return Response({'message': 'no available home slots'}, status=status.HTTP_409_CONFLICT)

        try:
            ElevatedOperations.add_home_user(available_home.home_index, request.user.username, s.validated_data['public_key'])
        except Exception:
            return Response({'message': 'failed to create tunnel user'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        HomeSerializer().update(available_home, {**s.validated_data, 'user': request.user})

        return Response(OutHomeSerializer(available_home).data, status=status.HTTP_201_CREATED)


class ProxyMappingListCreateView(ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ProxyMappingSerializer

    def get_queryset(self):
        return ProxyMapping.objects.filter(home__user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = ProxyMappingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        home = serializer.validated_data['home']
        if home.user != request.user:
            return Response({'message': 'forbidden'}, status=status.HTTP_403_FORBIDDEN)

        mapping = serializer.save()

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
    lookup_field = 'slug'

    def get_queryset(self):
        return ProxyMapping.objects.filter(home__user=self.request.user)

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
