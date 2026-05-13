import secrets

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group
from django.contrib.auth.views import LoginView as AuthLoginView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, get_object_or_404
from django.views.generic import FormView, TemplateView, View

from homes.models import Home, ProxyMapping
from homes.services import ElevatedOperations, HAProxyService
from homes.tunnels.manage_tunnel import tunnel_manager
from web.forms import SignupForm, RegisterHomeForm, AddMappingForm


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
            context['home_port_base'] = tunnel_manager.get_home_port_base(home.home_index)
            context['mappings'] = ProxyMapping.objects.filter(home=home)
        return context


class RegisterHomeView(HomeOwnerMixin, FormView):
    template_name = 'web/register_home.html'
    form_class = RegisterHomeForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and Home.objects.filter(user=request.user).exists():
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            available_home = Home.objects.select_for_update().filter(user__isnull=True).first()
            if not available_home:
                messages.error(self.request, 'No home slots are currently available.')
                return redirect('dashboard')

            try:
                ElevatedOperations.add_home_user(
                    available_home.home_index,
                    self.request.user.username,
                    form.cleaned_data['public_key'],
                )
            except Exception:
                messages.error(self.request, 'Failed to create tunnel user.')
                return redirect('dashboard')

            available_home.user = self.request.user
            available_home.public_key = form.cleaned_data['public_key']
            available_home.slug = secrets.token_urlsafe(16)
            available_home.save()

        messages.success(self.request, 'Home registered successfully.')
        return redirect('dashboard')


class EditHomeView(HomeOwnerMixin, FormView):
    template_name = 'web/edit_home.html'
    form_class = RegisterHomeForm

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


class AddMappingView(HomeOwnerMixin, FormView):
    template_name = 'web/add_mapping.html'
    form_class = AddMappingForm

    def get_home(self):
        return get_object_or_404(Home, user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['home'] = self.get_home()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        home = self.get_home()
        context['home'] = home
        port_base = tunnel_manager.get_home_port_base(home.home_index)
        context['home_port_base'] = port_base
        context['home_port_max'] = port_base + tunnel_manager.config.PORTS_PER_HOME - 1
        return context

    def form_valid(self, form):
        home = self.get_home()
        mapping = ProxyMapping.objects.create(
            home=home,
            host=form.cleaned_data['host'],
            tunnel_port=form.cleaned_data['tunnel_port'],
            scheme=form.cleaned_data['scheme'],
        )
        try:
            HAProxyService.add_mapping(mapping)
        except Exception:
            mapping.delete()
            messages.error(self.request, 'Failed to configure proxy.')
            return redirect('dashboard')

        messages.success(self.request, f'Proxy mapping for {mapping.host} added.')
        return redirect('dashboard')


class DeleteMappingView(HomeOwnerMixin, View):
    def post(self, request, host, *args, **kwargs):
        home = get_object_or_404(Home, user=request.user)
        mapping = get_object_or_404(ProxyMapping, host=host, home=home)
        try:
            HAProxyService.remove_mapping(mapping)
        except Exception:
            messages.error(request, 'Failed to remove proxy mapping.')
            return redirect('dashboard')

        mapping.delete()
        messages.success(request, f'Proxy mapping for {host} deleted.')
        return redirect('dashboard')
