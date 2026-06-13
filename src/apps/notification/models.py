from django.db import models
from django.urls import reverse_lazy

from jsonfield import JSONField

from apps.core.models import BaseModel
from apps.core.utils import random_str


def upload_notification_src(instance, path):
    frmt = str(path).split('.')[-1]
    return f'images/notifications/{random_str(20)}.{frmt}'


class NotificationConfig(BaseModel):
    """
        Singleton Model
    """
    send_sms_notify = models.BooleanField(default=True)
    send_email_notify = models.BooleanField(default=True)



class NotificationUser(BaseModel):
    """
        Notification for system user
    """
    type = models.CharField(max_length=100)
    title = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    # attach content
    image = models.ImageField(upload_to=upload_notification_src, null=True, blank=True, max_length=400)
    kwargs = JSONField(null=True, blank=True)

    send_notify = models.BooleanField(default=True)
    to_user = models.ForeignKey('account.User', on_delete=models.CASCADE)
    is_visited = models.BooleanField(default=False)

    class Meta:
        ordering = '-id',

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
