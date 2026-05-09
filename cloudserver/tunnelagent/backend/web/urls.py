from django.contrib.auth.views import LogoutView
from django.urls import path

from web.views import LandingView, SignupView, SignupPendingView, LoginView, DashboardView

urlpatterns = [
    path('', LandingView.as_view(), name='landing'),
    path('signup/', SignupView.as_view(), name='signup'),
    path('signup/pending/', SignupPendingView.as_view(), name='signup_pending'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
]
