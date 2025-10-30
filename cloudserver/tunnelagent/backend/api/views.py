import sys

from rest_framework.generics import ListAPIView, CreateAPIView, ListCreateAPIView, RetrieveDestroyAPIView
from rest_framework.views import APIView
from .models import ProxyMapping, Home
from .serializers import ProxyMappingSerializer, HomeSerializer
# from haproxyadmin.haproxy import HAProxy
from django.http import HttpRequest
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status



class HomeCreateView(APIView):
    # queryset = Home.objects.all()
    # serializer_class = HomeSerializer

    def post(self, request: HttpRequest):
        s = HomeSerializer(data=JSONParser().parse(request))
        if s.is_valid():
            validated_data = s.validated_data
            print('validated data:', s.validated_data, file=sys.stderr)
            available_home = Home.objects.filter(assigned=False).first()
            if not available_home:
                return Response({'message': 'no available home slots'}, status=status.HTTP_409_CONFLICT)

            validated_data['assigned'] = True
            s.update(available_home, validated_data)

            return Response({})
        else:
            return Response({}, status=status.HTTP_400_BAD_REQUEST)


class HomeDeleteView(APIView):
    def delete(self, request, pk):
        print('deleting home', pk)
        try:
            home = Home.objects.get(pk=pk)
        except Home.DoesNotExist as e:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if home.assigned:
            home.name = None
            home.public_key = None
            home.assigned = False
            home.save()
        return Response(status=status.HTTP_204_NO_CONTENT)



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












