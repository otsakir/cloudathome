from django.contrib.auth.views import LogoutView
from django.urls import path

from web.views import (
    LandingView, SignupView, SignupPendingView, LoginView, DashboardView,
    RegisterHomeView, EditHomeView, ReleaseHomeView, RotateTokenView, ClientConfigView,
    AddMappingView, DeleteMappingView,
)

urlpatterns = [
    path('', LandingView.as_view(), name='landing'),
    path('signup/', SignupView.as_view(), name='signup'),
    path('signup/pending/', SignupPendingView.as_view(), name='signup_pending'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('home/register/', RegisterHomeView.as_view(), name='register_home'),
    path('home/edit/', EditHomeView.as_view(), name='edit_home'),
    path('home/release/', ReleaseHomeView.as_view(), name='release_home'),
    path('home/token/rotate/', RotateTokenView.as_view(), name='rotate_token'),
    path('home/config/', ClientConfigView.as_view(), name='client_config'),
    path('home/mappings/add/', AddMappingView.as_view(), name='add_mapping'),
    path('home/mappings/<str:host>/delete/', DeleteMappingView.as_view(), name='delete_mapping'),
]
