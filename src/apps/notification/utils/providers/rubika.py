import logging

import requests

from django.conf import settings

from apps.notification.utils.providers import BaseProvider
from apps.notification.models import NotificationUser, NotificationConfig

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 3500


def _rubika_config(config=None):
    if config is None:
        config = settings.NOTIFICATION_RUBIKA_PROVIDER_CONFIG or {}
    return {
        'API_URL': (config.get('API_URL') or '').rstrip('/'),
        'BOT_TOKEN': config.get('BOT_TOKEN') or '',
        'TIMEOUT': config.get('TIMEOUT', 15),
    }


def _send_rubika_message(chat_id, text, config=None):
    cfg = _rubika_config(config)
    if not cfg['BOT_TOKEN'] or not cfg['API_URL']:
        logger.error('Rubika not configured: missing BOT_TOKEN or API_URL')
        return False

    try:
        resp = requests.post(
            url=f"{cfg['API_URL']}/{cfg['BOT_TOKEN']}/sendMessage",
            headers={'Content-Type': 'application/json'},
            json={'chat_id': str(chat_id), 'text': text[:MAX_MESSAGE_LENGTH]},
            timeout=cfg['TIMEOUT'],
        )
        if resp.status_code >= 400:
            logger.error('Rubika send failed status=%s body=%s', resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:
        logger.error('Rubika send exception: %s', exc)
        return False


class RubikaProvider(BaseProvider):
    config = settings.NOTIFICATION_RUBIKA_PROVIDER_CONFIG

    def _send(self, notification: NotificationUser) -> None:
        self.notification = notification

        notif_config = NotificationConfig.objects.first()
        if notif_config is not None and not notif_config.send_rubika_notify:
            logger.debug('Rubika skipped: NotificationConfig.send_rubika_notify is False')
            return

        try:
            message = self._get_message()
        except (AttributeError, TypeError) as exc:
            logger.warning(
                'Rubika message missing for type=%s notif_id=%s: %s',
                getattr(notification, 'type', None), notification.pk, exc,
            )
            return None

        if not message:
            logger.warning('Rubika message empty for type=%s notif_id=%s', notification.type, notification.pk)
            return None

        rubika_id = notification.to_user.rubika_id
        if not rubika_id:
            logger.warning('Rubika skipped: user %s has no rubika_id', notification.to_user_id)
            return None

        _send_rubika_message(rubika_id, message, self.config)

    def _get_message(self):
        notif_type = (self.notification.type or '').lower().strip()
        handler = getattr(self, f'_payload_{notif_type}', None)
        if handler is None:
            raise AttributeError(f'No Rubika payload handler for type={notif_type!r}')
        return handler()

    def _link_line(self):
        link = (self.notification.kwargs or {}).get('link') or ''
        return f'\nمشاهده: {link}' if link else ''

    def _payload_test(self):
        user = self.notification.to_user.get_full_name()
        return f'پیام آزمایشی آکوآدار\nکاربر: {user}'

    def _payload_irrigation_issue_report(self):
        kwargs = self.notification.kwargs or {}
        return (
            f"هشدار آبیاری: {self.notification.title}\n"
            f"باغ: {kwargs.get('farm', '')} | بخش: {kwargs.get('zone', '')} | "
            f"زمین: {kwargs.get('plot', '')} | ردیف: {kwargs.get('outlet', '')}\n"
            f"آبیار: {kwargs.get('waterman', '')}\n"
            f"مدت واقعی: {kwargs.get('actual_duration_min', '')} دقیقه "
            f"(مجاز: {kwargs.get('expected_min', '')} تا {kwargs.get('expected_max', '')} دقیقه)\n"
            f"انحراف: {kwargs.get('deviation_min', '')} دقیقه\n"
            f"زمان: {kwargs.get('time', '')}"
            f"{self._link_line()}"
        )

    def _payload_system_report(self):
        kwargs = self.notification.kwargs or {}
        body = self.notification.description or kwargs.get('summary', '')
        header = (
            f"گزارش سیستمی [{kwargs.get('priority_label', '')}] - {kwargs.get('category_label', '')}\n"
            f"{self.notification.title}\n"
        )
        return f'{header}\n{body}{self._link_line()}'

    def _payload_operation_event(self):
        kwargs = self.notification.kwargs or {}
        lines = [kwargs.get('event_label', self.notification.title)]
        if kwargs.get('farm'):
            lines.append(f"باغ: {kwargs['farm']}")
        if kwargs.get('plot'):
            lines.append(f"زمین: {kwargs['plot']}")
        if kwargs.get('details'):
            lines.append(kwargs['details'])
        lines.append(f"زمان: {kwargs.get('time', '')}")
        return '\n'.join(lines) + self._link_line()

    def _payload_logged_in(self):
        kwargs = self.notification.kwargs or {}
        return (
            f"ورود کاربر به آکوآدار\nکاربر: {kwargs.get('user', '')}\n"
            f"IP: {kwargs.get('ip', '')}\nزمان: {kwargs.get('time', '')}"
        )

    def _payload_logged_out(self):
        kwargs = self.notification.kwargs or {}
        return (
            f"خروج کاربر از آکوآدار\nکاربر: {kwargs.get('user', '')}\n"
            f"IP: {kwargs.get('ip', '')}\nزمان: {kwargs.get('time', '')}"
        )
