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
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse



class HomeRetrieveDestroyApiView(RetrieveDestroyAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = Home.objects.filter(assigned=True)
    serializer_class = OutHomeSerializer

    def destroy(self, request, pk, *args, **kwargs):
        home = self.get_object()

        try:
            ElevatedOperations.remove_home_user(home.home_index, home.name)
        except Exception:
            return Response({'message': 'failed to remove tunnel user'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        home.name = None
        home.public_key = None
        home.assigned = False
        home.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


class HomeListCreateAPIView(ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = Home.objects.filter(assigned=True)
    serializer_class = OutHomeSerializer

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

        available_home = Home.objects.filter(assigned=False).first()
        if not available_home:
            return Response({'message': 'no available home slots'}, status=status.HTTP_409_CONFLICT)

        try:
            ElevatedOperations.add_home_user(available_home.home_index, request.user.username, s.validated_data['public_key'])
        except Exception:
            return Response({'message': 'failed to create tunnel user'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        HomeSerializer().update(available_home, {**s.validated_data, 'name': request.user.username})

        return Response(OutHomeSerializer(available_home).data, status=status.HTTP_201_CREATED)


class ProxyMappingListCreateView(ListCreateAPIView):
    queryset = ProxyMapping.objects.all()
    serializer_class = ProxyMappingSerializer

    def create(self, request, *args, **kwargs):
        print("IN ProxyMapping create view")

        return super().create(request, *args, **kwargs)



class ProxyMappingDestroyAPIView(RetrieveDestroyAPIView):
    queryset = ProxyMapping.objects.all()
    serializer_class = ProxyMappingSerializer
    lookup_field = 'slug'


class ProxyInstanceAPIView(APIView):
    def get(self, request):
        print('in ProxyInstance GET')
        pass












