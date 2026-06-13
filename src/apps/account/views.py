from django.contrib.auth import authenticate, get_user_model, login, logout
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView, View
from django.urls import reverse_lazy
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.core.forms.utils import form_validate_err
from apps.core.utils import get_client_ip

from . import forms, models

User = get_user_model()


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

        # Create login activity
        models.UserLoginActivity.objects.create(
            user=user, ip=get_client_ip(request), agent=request.META['HTTP_USER_AGENT']
        )

        messages.success(request, _('Welcome'))
        return redirect('public:index')


class Logout(View):

    def get(self, request):
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
