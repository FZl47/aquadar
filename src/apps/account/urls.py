from django.urls import path

from . import views

app_name = 'account'

urlpatterns = [
    path('login', views.Login.as_view(), name='login'),
    path('logout', views.Logout.as_view(), name='logout'),
    path('reset-password', views.ResetPassword.as_view(), name='user_reset_password'),
]
