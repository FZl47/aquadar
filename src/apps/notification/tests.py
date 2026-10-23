from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import NotificationUser
from .utils.providers.rubika import RubikaProvider, _send_rubika_message
from .utils.providers.sms import SMSProvider

User = get_user_model()

SMS_CONFIG = {'API_TOKEN': 'tok', 'API_URL': 'https://sms.test/send', 'PATTERN_API_URL': 'https://sms.test/pattern',
              'LINE_NUMBER': '1000'}
RUBIKA_CONFIG = {'BOT_TOKEN': 'bot', 'API_URL': 'https://rubika.test', 'TIMEOUT': 3}


class NotificationProviderBase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='u1', password='x', role='supervisor', phonenumber='09120000000', rubika_id='b0xyz',
            first_name='علی', last_name='رضایی',
        )

    def make_notif(self, type_notif, title='عنوان', description='متن', **kwargs_notif):
        with mock.patch('apps.notification.utils.providers.base.BaseProvider.send'):
            return NotificationUser.objects.create(
                to_user=self.user, type=type_notif, title=title, description=description, kwargs=kwargs_notif,
            )


class SMSProviderTests(NotificationProviderBase):

    def provider(self, notif):
        provider = SMSProvider.__new__(SMSProvider)
        provider.config = SMS_CONFIG
        provider.notification = notif
        return provider

    def test_system_report_payload(self):
        notif = self.make_notif(
            'system_report', category_label='تحلیل زمین', priority_label='بالا', farm='باغ', plot='زمین',
            detail_url='https://x/r/1/',
        )
        code, variables = self.provider(notif)._get_payload()
        self.assertEqual(code, 'aq_report')
        self.assertEqual(variables['category'], 'تحلیل زمین')
        self.assertEqual(variables['priority'], 'بالا')
        self.assertEqual(variables['link'], 'https://x/r/1/')

    def test_operation_event_filtered(self):
        sent = self.make_notif('operation_event', event='fertilization_registered', event_label='کوددهی', user='علی')
        skipped = self.make_notif('operation_event', event='irrigation_started')
        self.assertEqual(self.provider(sent)._get_payload()[0], 'aq_event')
        self.assertIsNone(self.provider(skipped)._get_payload())

    def test_send_posts_pattern_sms(self):
        notif = self.make_notif('system_report', category_label='ک', priority_label='کم')
        provider = self.provider(notif)
        with mock.patch('apps.notification.utils.providers.sms.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = '{}'
            post.return_value.json.return_value = {}
            provider._send(notif)
        self.assertTrue(post.called)


class RubikaProviderTests(NotificationProviderBase):

    def provider(self, notif):
        provider = RubikaProvider.__new__(RubikaProvider)
        provider.config = RUBIKA_CONFIG
        provider.notification = notif
        return provider

    def test_system_report_message(self):
        notif = self.make_notif(
            'system_report', description='گزارش کامل', priority_label='بالا', category_label='آبیاری',
            link='https://x/r/1/',
        )
        message = self.provider(notif)._get_message()
        self.assertIn('گزارش سیستمی [بالا] - آبیاری', message)
        self.assertIn('گزارش کامل', message)
        self.assertIn('مشاهده: https://x/r/1/', message)

    def test_operation_event_message(self):
        notif = self.make_notif(
            'operation_event', event_label='شروع آبیاری', farm='باغ', plot='زمین', details='ردیف 3', time='10:00',
        )
        message = self.provider(notif)._get_message()
        self.assertIn('شروع آبیاری', message)
        self.assertIn('باغ: باغ', message)
        self.assertIn('ردیف 3', message)

    def test_send_posts_to_rubika(self):
        notif = self.make_notif('system_report', priority_label='کم', category_label='ک')
        with mock.patch('apps.notification.utils.providers.rubika.requests.post') as post:
            post.return_value.status_code = 200
            self.provider(notif)._send(notif)
        self.assertEqual(post.call_args.kwargs['url'], 'https://rubika.test/bot/sendMessage')
        self.assertEqual(post.call_args.kwargs['json']['chat_id'], 'b0xyz')

    def test_user_without_rubika_id_skipped(self):
        self.user.rubika_id = ''
        self.user.save()
        notif = self.make_notif('system_report', priority_label='کم', category_label='ک')
        with mock.patch('apps.notification.utils.providers.rubika.requests.post') as post:
            self.provider(notif)._send(notif)
        post.assert_not_called()

    def test_http_error_returns_false(self):
        with mock.patch('apps.notification.utils.providers.rubika.requests.post') as post:
            post.return_value.status_code = 500
            post.return_value.text = 'err'
            self.assertFalse(_send_rubika_message('c', 'hi', RUBIKA_CONFIG))
