from rest_framework.generics import ListAPIView, CreateAPIView, ListCreateAPIView
from .models import ProxyMapping
from .serializers import ProxyMappingSerializer


class ProxyMappingListCreateView(ListCreateAPIView):
    queryset = ProxyMapping.objects.all()
    serializer_class = ProxyMappingSerializer

    def create(self, request, *args, **kwargs):
        print("IN ProxyMapping create view")

        return super().create(request, *args, **kwargs)










