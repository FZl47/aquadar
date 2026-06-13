import json
import requests

from django.conf import settings

from apps.notification.utils.providers import BaseProvider
from apps.notification.models import NotificationUser, NotificationConfig


def _send_sms(phonenumber, message, config=None):
    if config is None:
        config = settings.NOTIFICATION_SMS_PROVIDER_CONFIG

    phonenumber = str(phonenumber).replace('+', '')

    payload = json.dumps({
        "message": message,
        "recipients": [phonenumber],
        "sourceNumber": config['LINE_NUMBER'],
    })

    headers = {
        "Authorization": f"Bearer {config['API_TOKEN']}",
        "Content-Type": "application/json",
    }

    requests.post(
        url=config['API_URL'],
        headers=headers,
        data=payload
    )


def _send_pattern_sms(phonenumber, pattern_code, variables, config=None):
    if config is None:
        config = settings.NOTIFICATION_SMS_PROVIDER_CONFIG

    phonenumber = str(phonenumber).replace('+', '')

    payload = json.dumps({
        "pattern_code": pattern_code,
        "originator": config['LINE_NUMBER'],
        "recipient": phonenumber,
        "values": variables,
    })

    headers = {
        "Authorization": f"Bearer {config['API_TOKEN']}",
        "Content-Type": "application/json",
    }

    requests.post(
        url=config.get('PATTERN_API_URL', config['API_URL']),
        headers=headers,
        data=payload
    )


class SMSProvider(BaseProvider):
    config = settings.NOTIFICATION_SMS_PROVIDER_CONFIG

    def _send(self, notification: NotificationUser) -> None:
        self.notification = notification

        notif_config = NotificationConfig.objects.first()
        if notif_config is not None and not notif_config.send_sms_notify:
            return

        try:
            result = self._get_payload()
        except (AttributeError, TypeError):
            return None

        if not result:
            return None

        pattern_code, variables = result

        phonenumber = notification.to_user.phonenumber
        if not phonenumber:
            return None

        _send_pattern_sms(phonenumber, pattern_code, variables, self.config)

    def _get_payload(self):
        notif_type = self.notification.type.lower()
        return getattr(self, f'_payload_{notif_type}')()

    def _payload_test(self):
        return None

    def _payload_irrigation_issue_report(self):
        kwargs = self.notification.kwargs
        # TODO: Should be complete with all the variables needed for the pattern
        return ('irg_alert', {
            'waterman': kwargs.get('waterman', ''),
            'farm': kwargs.get('farm', ''),
            'zone': kwargs.get('zone', ''),
            'plot': kwargs.get('plot', ''),
            'outlet': kwargs.get('outlet', ''),
        })
