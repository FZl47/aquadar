import json
import logging

import requests

from django.conf import settings

from apps.notification.utils.providers import BaseProvider
from apps.notification.models import NotificationUser, NotificationConfig

logger = logging.getLogger(__name__)


def _sms_config(config=None):
    """Normalize SMS provider settings (supports API_TOKEN or API_KEY)."""
    if config is None:
        config = settings.NOTIFICATION_SMS_PROVIDER_CONFIG or {}
    token = config.get('API_TOKEN') or config.get('API_KEY') or ''
    return {
        'API_TOKEN': token,
        'API_URL': config.get('API_URL') or '',
        'PATTERN_API_URL': config.get('PATTERN_API_URL') or config.get('API_URL') or '',
        'LINE_NUMBER': config.get('LINE_NUMBER') or '',
    }


def _str_vars(variables):
    """Pattern SMS APIs require string values."""
    return {str(k): '' if v is None else str(v) for k, v in (variables or {}).items()}


def _send_sms(phonenumber, message, config=None):
    cfg = _sms_config(config)
    if not cfg['API_TOKEN'] or not cfg['API_URL']:
        logger.error('SMS not configured: missing API_TOKEN/API_KEY or API_URL')
        return False

    phonenumber = str(phonenumber).replace('+', '')

    payload = json.dumps({
        "message": message,
        "recipients": [phonenumber],
        "sourceNumber": cfg['LINE_NUMBER'],
    })

    headers = {
        "Authorization": f"Bearer {cfg['API_TOKEN']}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url=cfg['API_URL'], headers=headers, data=payload, timeout=15)
        if resp.status_code >= 400:
            logger.error('SMS plain send failed status=%s body=%s', resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:
        logger.error('SMS plain send exception: %s', exc)
        return False


def _send_pattern_sms(phonenumber, pattern_code, variables, config=None):
    cfg = _sms_config(config)
    if not cfg['API_TOKEN']:
        logger.error('SMS pattern send skipped: missing API_TOKEN/API_KEY')
        return False

    url = cfg['PATTERN_API_URL'] or cfg['API_URL']
    if not url:
        logger.error('SMS pattern send skipped: missing API_URL')
        return False

    phonenumber = str(phonenumber).replace('+', '')

    payload = json.dumps({
        "pattern_code": pattern_code,
        "originator": cfg['LINE_NUMBER'],
        "recipient": phonenumber,
        "values": _str_vars(variables),
    })

    headers = {
        "Authorization": f"Bearer {cfg['API_TOKEN']}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url=url, headers=headers, data=payload, timeout=15)
        if resp.status_code >= 400:
            logger.error(
                'SMS pattern send failed code=%s status=%s body=%s',
                pattern_code, resp.status_code, resp.text[:300],
            )
            return False
        logger.info('SMS pattern sent code=%s to=%s status=%s', pattern_code, phonenumber, resp.status_code)
        return True
    except Exception as exc:
        logger.error('SMS pattern send exception code=%s: %s', pattern_code, exc)
        return False


class SMSProvider(BaseProvider):
    config = settings.NOTIFICATION_SMS_PROVIDER_CONFIG

    def _send(self, notification: NotificationUser) -> None:
        self.notification = notification

        notif_config = NotificationConfig.objects.first()
        if notif_config is not None and not notif_config.send_sms_notify:
            logger.debug('SMS skipped: NotificationConfig.send_sms_notify is False')
            return

        try:
            result = self._get_payload()
        except (AttributeError, TypeError) as exc:
            logger.warning(
                'SMS payload missing for type=%s notif_id=%s: %s',
                getattr(notification, 'type', None), notification.pk, exc,
            )
            return None

        if not result:
            logger.warning('SMS payload empty for type=%s notif_id=%s', notification.type, notification.pk)
            return None

        pattern_code, variables = result

        phonenumber = notification.to_user.phonenumber
        if not phonenumber:
            logger.warning('SMS skipped: user %s has no phonenumber', notification.to_user_id)
            return None

        _send_pattern_sms(phonenumber, pattern_code, variables, self.config)

    def _get_payload(self):
        notif_type = (self.notification.type or '').lower().strip()
        handler = getattr(self, f'_payload_{notif_type}', None)
        if handler is None:
            raise AttributeError(f'No SMS payload handler for type={notif_type!r}')
        return handler()

    def _payload_test(self):
        return None

    def _payload_irrigation_issue_report(self):
        kwargs = self.notification.kwargs or {}
        return ('irg_alert', {
            'waterman': kwargs.get('waterman', ''),
            'farm': kwargs.get('farm', ''),
            'zone': kwargs.get('zone', ''),
            'plot': kwargs.get('plot', ''),
            'outlet': kwargs.get('outlet', ''),
        })

    def _payload_plot_health_alert(self):
        """SMS for plot health score falling below RunSettings.min_health_score."""
        kwargs = self.notification.kwargs or {}
        return ('irg_alert', {
            'waterman': kwargs.get('health_score', kwargs.get('score', '')),
            'farm': kwargs.get('farm', ''),
            'zone': kwargs.get('zone', ''),
            'plot': kwargs.get('plot', ''),
            'outlet': kwargs.get('summary', kwargs.get('health_score', ''))[:40],
        })

    def _payload_logged_in(self):
        kwargs = self.notification.kwargs or {}
        return ('drnv3', {
            'user': kwargs.get('user', ''),
            'ip': kwargs.get('ip', ''),
            'time': kwargs.get('time', ''),
        })

    def _payload_logged_out(self):
        kwargs = self.notification.kwargs or {}
        return ('u04sa', {
            'user': kwargs.get('user', ''),
            'ip': kwargs.get('ip', ''),
            'time': kwargs.get('time', ''),
        })
