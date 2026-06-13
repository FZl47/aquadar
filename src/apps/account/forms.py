from django.utils.translation import gettext_lazy as _
from django import forms


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField()


class UserResetPasswordForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput())
    new_password = forms.CharField(widget=forms.PasswordInput())
    confirm_new_password = forms.CharField(widget=forms.PasswordInput())

    def clean(self):
        c = super().clean()
        data = self.cleaned_data
        new_password = data.get('new_password')
        confirm_new_password = data.get('confirm_new_password')
        if new_password and confirm_new_password and new_password != confirm_new_password:
            self.add_error('confirm_new_password', _('Passwords not same'))
        return c