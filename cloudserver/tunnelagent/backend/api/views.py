from rest_framework.generics import ListAPIView, CreateAPIView, ListCreateAPIView, RetrieveDestroyAPIView
from rest_framework.views import APIView
from .models import ProxyMapping
from .serializers import ProxyMappingSerializer
# from haproxyadmin.haproxy import HAProxy


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












