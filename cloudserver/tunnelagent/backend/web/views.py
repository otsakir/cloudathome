from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group
from django.contrib.auth.views import LoginView as AuthLoginView
from django.shortcuts import redirect
from django.views.generic import FormView, TemplateView

from homes.models import Home
from homes.tunnels.manage_tunnel import tunnel_manager
from web.forms import SignupForm


class LandingView(TemplateView):
    template_name = 'web/landing.html'


class SignupView(FormView):
    template_name = 'web/signup.html'
    form_class = SignupForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=form.cleaned_data['email'],
            first_name=form.cleaned_data['full_name'],
            password=form.cleaned_data['password'],
            is_active=False,
        )
        user.groups.add(Group.objects.get(name='homeowner'))
        return redirect('signup_pending')


class SignupPendingView(TemplateView):
    template_name = 'web/signup_pending.html'


class LoginView(AuthLoginView):
    template_name = 'web/login.html'


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'web/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        home = Home.objects.filter(user=self.request.user).first()
        context['home'] = home
        if home:
            context['home_port_base'] = tunnel_manager.get_home_port_base(home.home_index)
        return context
