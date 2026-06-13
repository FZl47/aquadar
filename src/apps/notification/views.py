from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, TemplateView
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Q, Value, CharField
from django.db.models.functions import Concat

from apps.core.utils import c_bool
from apps.core.views.mixins import (
    CreateViewMixin, DetailViewMixin, ListViewMixin
)
from apps.core.auth.permissions.mixins import PermissionMixin

User = get_user_model()

from . import forms, models


class SeenAll(LoginRequiredMixin, View):

    def get_redirect_url(self):
        return self.request.META.get('HTTP_REFERER', '/')

    def get(self, request):
        user = request.user
        user.get_unread_notifications().update(is_visited=True)
        return redirect(self.get_redirect_url())


class NotificationCreate(PermissionMixin, CreateViewMixin, TemplateView):
    template_name = 'notification/create.html'
    permissions = ('notification.add_notificationuser',)
    form = forms.NotificationUserCreateForm

    def get_context_data(self, **kwargs):
        return {
            'users': User.objects.filter(is_active=True).exclude(id=self.request.user.id)
        }

    def additional_data(self):
        return {
            'type': 'CUSTOM_NOTIFICATION'
        }

    def post(self, request):
        return self.create(request)


class NotificationList(PermissionMixin, ListViewMixin, TemplateView):
    template_name = 'notification/list.html'
    permissions = ('notification.view_notificationuser',)

    def get_queryset(self):
        qs = models.NotificationUser.objects.all().annotate(
            user_full_name=Concat('to_user__first_name', Value(' '), 'to_user__last_name', output_field=CharField()))
        return self.filter(qs)

    def filter(self, qs):
        params = self.request.GET

        sort_by = params.get('sort_by', 'latest')
        if sort_by == 'latest':
            qs = qs.order_by('-id')
        else:
            qs = qs.order_by('id')

        search = params.get('search')
        if search:
            lookup = Q(user_full_name__icontains=search) | Q(title__icontains=search)
            qs = qs.filter(lookup)

        is_visited = params.get('is_visited', 'all')
        if is_visited != 'all':
            qs = qs.filter(is_visited=c_bool(is_visited))

        return qs

    def get(self, request, *args, **kwargs):
        return self.list(request)


class NotificationPersonalList(LoginRequiredMixin, ListViewMixin, TemplateView):
    template_name = 'notification/personal-list.html'

    def get_queryset(self):
        return self.filter(self.request.user.get_notifications())

    def filter(self, qs):
        params = self.request.GET

        sort_by = params.get('sort_by', 'latest')
        if sort_by == 'latest':
            qs = qs.order_by('-id')
        else:
            qs = qs.order_by('id')

        search = params.get('search')
        if search:
            lookup = Q(title__icontains=search)
            qs = qs.filter(lookup)

        is_visited = params.get('is_visited', 'all')
        if is_visited != 'all':
            qs = qs.filter(is_visited=c_bool(is_visited))

        return qs

    def get(self, request, *args, **kwargs):
        return self.list(request)


class NotificationDetail(LoginRequiredMixin, DetailViewMixin, TemplateView):
    template_name = 'notification/detail.html'

    def get_instance(self, **kwargs):
        user = self.request.user
        should_update_visit = False
        if user.has_perm('notification.view_notificationuser'):
            obj = get_object_or_404(models.NotificationUser, id=self.kwargs['pk'])
            if obj.to_user == user:
                should_update_visit = True
        else:
            obj = get_object_or_404(models.NotificationUser, id=self.kwargs['pk'], to_user=user)
            should_update_visit = True

        if should_update_visit:
            # Update visit status
            obj.is_visited = True
            obj.save(update_fields=['is_visited'])

        return obj
