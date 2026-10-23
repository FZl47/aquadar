from django.db import models
from django.db.models import JSONField
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel
from apps.core.utils import random_str


def upload_notification_src(instance, path):
    frmt = str(path).split('.')[-1]
    return f'images/notifications/{random_str(20)}.{frmt}'


class NotificationConfig(BaseModel):
    send_sms_notify = models.BooleanField(default=True, verbose_name=_('Send SMS Notification'))
    send_email_notify = models.BooleanField(default=True, verbose_name=_('Send Email Notification'))
    send_rubika_notify = models.BooleanField(default=True, verbose_name=_('Send Rubika Notification'))

    class Meta:
        verbose_name = _('Notification Config')
        verbose_name_plural = _('Notification Configs')



class NotificationUser(BaseModel):
    type = models.CharField(max_length=100, verbose_name=_('Type'))
    title = models.CharField(max_length=150, verbose_name=_('Title'))
    description = models.TextField(null=True, blank=True, verbose_name=_('Description'))
    image = models.ImageField(upload_to=upload_notification_src, null=True, blank=True, max_length=400,
                              verbose_name=_('Image'))
    kwargs = JSONField(null=True, blank=True, verbose_name=_('Extra Data (JSON)'))
    send_notify = models.BooleanField(default=True, verbose_name=_('Send Notify'))
    to_user = models.ForeignKey('account.User', on_delete=models.CASCADE, verbose_name=_('User'))
    is_visited = models.BooleanField(default=False, verbose_name=_('Visited'))

    class Meta:
        ordering = '-id',
        verbose_name = _('User Notification')
        verbose_name_plural = _('User Notifications')

    def __str__(self):
        return f'{self.to_user} / {self.title}'

    def get_absolute_url(self):
        return reverse_lazy('notification:notification__detail', args=(self.id,))

    def get_link(self):
        try:
            link = self.kwargs['link']
            return link
        except (KeyError, TypeError):
            return None

    def get_image(self):
        try:
            return self.image.url
        except (AttributeError, ValueError):
            return None
