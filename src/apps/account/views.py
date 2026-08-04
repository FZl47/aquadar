from django.contrib.auth import authenticate, get_user_model, login, logout
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView, View
from django.urls import reverse_lazy
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.core.forms.utils import form_validate_err
from apps.core.utils import get_client_ip
from apps.notification.utils import create_user_notif

from . import forms, models

User = get_user_model()


def _notify_admins_auth_event(user, notif_type, title, description, **extra_kwargs):
    """login/logout event."""
    kwargs_notif = {
        'user': user.get_full_name() or user.username,
        'username': user.username,
        **extra_kwargs,
    }
    for admin in User.objects.filter(is_superuser=True):
        create_user_notif(
            to_user=admin,
            type_notif=notif_type,
            title=title,
            description=description,
            kwargs_notif=dict(kwargs_notif),
        )


class Login(TemplateView):
    template_name = 'account/login.html'
    form = forms.LoginForm

    def post(self, request):
        data = request.POST
        f = self.form(data)
        if not form_validate_err(request, f):
            return redirect('account:login')

        username = data['username']
        password = data['password']
        user = authenticate(request, username=username, password=password)
        if not user:
            messages.error(request, _('User not found'))
            return redirect('account:login')

        login(request, user)

        ip = get_client_ip(request)
        agent = request.META.get('HTTP_USER_AGENT', '')

        # Create login activity
        models.UserLoginActivity.objects.create(
            user=user, ip=ip, agent=agent
        )

        display_name = user.get_full_name() or user.username
        _notify_admins_auth_event(
            user,
            'logged_in',
            _('User logged in'),
            _('User %(user)s (%(username)s) logged in from IP %(ip)s') % {
                'user': display_name,
                'username': user.username,
                'ip': ip,
            },
            ip=ip,
            agent=agent,
        )

        messages.success(request, _('Welcome'))
        return redirect('public:index')


class Logout(View):

    def get(self, request):
        user = request.user
        if user.is_authenticated:
            ip = get_client_ip(request)
            agent = request.META.get('HTTP_USER_AGENT', '')
            display_name = user.get_full_name() or user.username
            _notify_admins_auth_event(
                user,
                'logged_out',
                _('User logged out'),
                _('User %(user)s (%(username)s) logged out from IP %(ip)s') % {
                    'user': display_name,
                    'username': user.username,
                    'ip': ip,
                },
                ip=ip,
                agent=agent,
            )
        logout(request)
        return redirect('account:login')



class ResetPassword(LoginRequiredMixin, View):
    form = forms.UserResetPasswordForm
    redirect_url = reverse_lazy('public:index')

    def post(self, request):
        f = self.form(data=request.POST)
        if not form_validate_err(request, f):
            return redirect(self.redirect_url)

        data = f.cleaned_data
        user = request.user

        current_password = data['current_password']
        new_password = data['confirm_new_password']

        # Check current password
        if not user.check_password(current_password):
            messages.error(request, _('Current password is wrong'))
            return redirect(self.redirect_url)
        user.set_password(new_password)
        messages.success(request, _('Your password changed successfully!'))
        logout(request)
        return redirect('account:login')

    def get_instance(self):
        return self.request.user
