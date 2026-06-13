from django.urls import path

from . import views

app_name = 'apps.notification'

urlpatterns = [
    path('notification/seen-all', views.SeenAll.as_view(), name='seen_all'),
    path('notification/create', views.NotificationCreate.as_view(), name='notification__create'),
    path('notification/list/personal', views.NotificationPersonalList.as_view(), name='notification_personal__list'),
    path('notification/list', views.NotificationList.as_view(), name='notification__list'),
    path('notification/<int:pk>/detail', views.NotificationDetail.as_view(), name='notification__detail'),
]
