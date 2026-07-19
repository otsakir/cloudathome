from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group
from django.contrib.auth.views import LoginView as AuthLoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render, get_object_or_404
from django.views.generic import FormView, TemplateView, View

from tunnels.models import Home
from tunnels.services import ElevatedOperations, HAProxyService
from tunnels.ssh.manage_home import tunnel_manager
from web.forms import SignupForm, UpdatePublicKeyForm
from web.services import HomeConfigService


class HomeOwnerMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.groups.filter(name='homeowner').exists():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


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
        context['ssh_host'] = self.request.get_host().split(':')[0]
        if home:
            port_base = tunnel_manager.get_home_port_base(home.home_index)
            context['home_port_base'] = port_base
            context['mappings'] = HAProxyService.get_home_mappings(port_base, tunnel_manager.config.PORTS_PER_HOME)
        else:
            context['has_token'] = HomeConfigService.has_token(self.request.user)
            context['cloudserver_url'] = self.request.build_absolute_uri('/').rstrip('/')
        return context


class EditHomeView(HomeOwnerMixin, FormView):
    template_name = 'web/edit_home.html'
    form_class = UpdatePublicKeyForm

    def get_home(self):
        return get_object_or_404(Home, user=self.request.user)

    def get_initial(self):
        return {'public_key': self.get_home().public_key}

    def form_valid(self, form):
        home = self.get_home()
        try:
            ElevatedOperations.update_home_user_key(
                home.home_index,
                self.request.user.username,
                form.cleaned_data['public_key'],
            )
        except Exception:
            messages.error(self.request, 'Failed to update public key.')
            return redirect('dashboard')

        home.public_key = form.cleaned_data['public_key']
        home.save()

        messages.success(self.request, 'Public key updated.')
        return redirect('dashboard')


class ReleaseHomeView(HomeOwnerMixin, TemplateView):
    template_name = 'web/release_home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['home'] = get_object_or_404(Home, user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        home = get_object_or_404(Home, user=request.user)
        try:
            ElevatedOperations.remove_home_user(home.home_index, home.user.username)
        except Exception:
            messages.error(request, 'Failed to remove tunnel user.')
            return redirect('dashboard')

        home.user = None
        home.public_key = None
        home.slug = None
        home.save()

        messages.success(request, 'Home released.')
        return redirect('dashboard')


class ClientConfigView(HomeOwnerMixin, TemplateView):
    template_name = 'web/client_config.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        home = get_object_or_404(Home, user=self.request.user)
        context['home'] = home
        context['config_yaml'] = HomeConfigService.build_yaml(self.request, home)
        return context


class RotateTokenView(HomeOwnerMixin, TemplateView):
    """Generates a fresh API token, whether or not a home is registered yet.
    rotate_token() deletes any existing token first, so this is also how a
    user gets their very first token -- there's no separate "generate" flow."""
    template_name = 'web/rotate_token.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['home'] = Home.objects.filter(user=self.request.user).first()
        return context

    def post(self, request, *args, **kwargs):
        home = Home.objects.filter(user=request.user).first()
        token = HomeConfigService.rotate_token(request.user)
        messages.success(request, 'Token rotated. The old token no longer works.')
        return render(request, 'web/token_rotated.html', {
            'home': home,
            'token': token.key,
            'cloudserver_url': request.build_absolute_uri('/').rstrip('/'),
        })


