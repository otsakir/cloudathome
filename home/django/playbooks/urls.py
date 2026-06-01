from django.urls import path
from .views import PlaybookIndexView, IssueCertificateView

urlpatterns = [
    path('', PlaybookIndexView.as_view(), name='playbook_index'),
    path('issue-certificate/', IssueCertificateView.as_view(), name='playbook_issue_certificate'),
]
