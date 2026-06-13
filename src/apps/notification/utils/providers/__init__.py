from django.conf import settings
from django.utils.module_loading import import_string

from .base import BaseProvider
from .sms import SMSProvider
from .email import EmailProvider


def get_selected_providers():
    providers = settings.NOTIFICATION_CONFIG['PROVIDERS']
    try:
        return [import_string(p) for p in providers]
    except Exception as e:
        raise