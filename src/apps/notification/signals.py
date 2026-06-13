from django.db.models.signals import post_save
from django.dispatch import receiver

from .utils.providers import get_selected_providers

from . import models

@receiver(post_save, sender=models.NotificationUser)
def handle_notification_users_notify(sender, instance, created, **kwargs):
    """
    Dispatch notifications after saving a NotificationUser instance.

    If `send_notify` is enabled, the notification is sent using
    all configured notification providers.
    """
    if not instance.send_notify:
        return

    for provider in get_selected_providers():
        provider(instance).send()
