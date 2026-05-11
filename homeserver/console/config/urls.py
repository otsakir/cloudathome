from django.urls import path
from .views import SetupWizardView, DashboardView

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('setup/', SetupWizardView.as_view(), name='setup'),
]
