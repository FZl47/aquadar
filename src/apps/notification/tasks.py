from celery import shared_task
from django.utils.module_loading import import_string

from .models import NotificationUser


@shared_task
def send_notification_via_provider(provider_class_path: str, notification_id: int) -> None:
    try:
        notification = NotificationUser.objects.get(pk=notification_id)
    except NotificationUser.DoesNotExist:
        return

    provider_class = import_string(provider_class_path)
    provider = provider_class(notification)
    provider._send_wrapper(notification)
