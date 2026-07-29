from django.urls import path, include
from webpages.views import GuidesView

urlpatterns = [
    path('guides/', GuidesView.as_view(), name='guides'),
]