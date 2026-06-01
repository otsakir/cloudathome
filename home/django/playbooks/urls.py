from django.urls import path
from .views import IssueCertificateView

urlpatterns = [
    path('issue-certificate/', IssueCertificateView.as_view(), name='playbook_issue_certificate'),
]
