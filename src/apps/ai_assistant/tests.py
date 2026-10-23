import datetime
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.public.models import Experiment

from .models import AIProviderConfig, AISettings, ExperimentAnalysis
from .providers.base import KIND_IMAGE, KIND_PDF, Attachment, ProviderError
from .providers.registry import PROVIDER_CLASSES, get_provider, provider_choices
from .reports import build_experiment_report, build_leaf_report
from .services import get_main_provider_name, parse_json_response, run_experiment_analysis

User = get_user_model()

TEMP_MEDIA_ROOT = tempfile.mkdtemp()

AI_CONFIG = {
    'DEFAULT_PROVIDER': 'gemini',
    'TIMEOUT': 5,
    'PROVIDERS': {
        'gemini': {'API_KEY': 'g-key', 'MODEL': 'gemini-test'},
        'claude': {'API_KEY': 'c-key', 'MODEL': 'claude-test'},
        'chatgpt': {'API_KEY': '', 'MODEL': 'gpt-test'},
    },
}

VALID_RESULT = (
    '{"summary": "خلاصه", "urgency": "high", "soil": {"status": "ok", "findings": [], "issues": []},'
    ' "irrigation": ["آبیاری عمیق"], "fertilization": [], "spraying": []}'
)


class ParseJsonResponseTests(SimpleTestCase):

    def test_plain_json(self):
        self.assertEqual(parse_json_response('{"a": 1}'), {'a': 1})

    def test_fenced_json(self):
        self.assertEqual(parse_json_response('```json\n{"a": 1}\n```'), {'a': 1})

    def test_json_with_surrounding_text(self):
        self.assertEqual(parse_json_response('نتیجه: {"a": 1} پایان'), {'a': 1})

    def test_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_json_response('no json here')


@override_settings(AI_ASSISTANT_CONFIG=AI_CONFIG)
class ProviderRegistryTests(TestCase):

    def test_all_requested_providers_registered(self):
        for name in ('chatgpt', 'gapgpt', 'grok', 'claude', 'gemini', 'deepseek'):
            self.assertIn(name, PROVIDER_CLASSES)

    def test_config_is_applied(self):
        provider = get_provider('claude')
        self.assertEqual(provider.model, 'claude-test')
        self.assertTrue(provider.is_configured)
        self.assertFalse(get_provider('chatgpt').is_configured)

    def test_unknown_provider(self):
        with self.assertRaises(ProviderError):
            get_provider('unknown')

    def test_db_config_overrides_builtin_provider(self):
        AIProviderConfig.objects.create(
            key='claude', label='Claude داخلی', provider_type='claude', api_key='db-key', model='claude-db')
        provider = get_provider('claude')
        self.assertEqual(provider.model, 'claude-db')
        self.assertEqual(provider.api_key, 'db-key')
        self.assertEqual(provider.label, 'Claude داخلی')
        self.assertFalse(provider.is_custom)

    def test_inactive_db_config_is_ignored(self):
        AIProviderConfig.objects.create(
            key='claude', label='x', provider_type='claude', api_key='db-key', model='claude-db', is_active=False)
        self.assertEqual(get_provider('claude').model, 'claude-test')

    def test_custom_provider_is_listed_and_built(self):
        AIProviderConfig.objects.create(
            key='my-llm', label='سرویس من', provider_type='chatgpt', api_key='k', model='m',
            base_url='https://llm.example.com/v1')
        provider = get_provider('my-llm')
        self.assertTrue(provider.is_custom)
        self.assertEqual(provider.base_url, 'https://llm.example.com/v1')
        self.assertIn(('my-llm', 'سرویس من'), provider_choices())

    def test_unsupported_attachments_become_text(self):
        deepseek = get_provider('deepseek')
        image = Attachment(label='خاک', filename='a.jpg', kind=KIND_IMAGE, mime_type='image/jpeg', data=b'x')
        pdf = Attachment(label='برگ', filename='a.pdf', kind=KIND_PDF, mime_type='application/pdf', data=b'x', text='N 2')
        self.assertFalse(deepseek.is_native_attachment(image))
        self.assertFalse(deepseek.is_native_attachment(pdf))
        self.assertIn('N 2', deepseek.attachment_as_text(pdf))
        self.assertIn('در دسترس نیست', deepseek.attachment_as_text(image))
        self.assertTrue(get_provider('gemini').is_native_attachment(pdf))


@override_settings(AI_ASSISTANT_CONFIG=AI_CONFIG, MEDIA_ROOT=TEMP_MEDIA_ROOT)
class AnalysisServiceTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.experiment = Experiment.objects.create(
            name='آزمایش', date=datetime.date(2025, 8, 1),
            soil_file=SimpleUploadedFile('soil.txt', b'EC=3.2 pH=7.8'),
            leaf_file=SimpleUploadedFile('leaf.csv', b'N,1.45'),
            water_file=SimpleUploadedFile('water.txt', b'EC=2'),
        )

    def _analysis(self, provider='gemini'):
        return ExperimentAnalysis.objects.create(experiment=self.experiment, provider=provider)

    def test_main_provider_prefers_db_setting(self):
        self.assertEqual(get_main_provider_name(), 'gemini')
        settings_obj = AISettings.get_solo()
        settings_obj.main_provider = 'claude'
        settings_obj.save()
        self.assertEqual(get_main_provider_name(), 'claude')

    def test_successful_analysis_is_stored(self):
        analysis = self._analysis()
        with mock.patch('apps.ai_assistant.providers.gemini.GeminiProvider.generate', return_value=VALID_RESULT) as gen:
            outcome = run_experiment_analysis(analysis.pk)
        self.assertTrue(outcome['success'])
        attachments = gen.call_args.args[2]
        self.assertEqual(len(attachments), 3)
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, ExperimentAnalysis.STATUS_DONE)
        self.assertEqual(analysis.urgency, 'high')
        self.assertEqual(analysis.result['irrigation'], ['آبیاری عمیق'])
        self.assertEqual(analysis.model_name, 'gemini-test')
        self.assertIsNotNone(analysis.analyzed_at)

    def test_missing_api_key_marks_error(self):
        analysis = self._analysis('chatgpt')
        outcome = run_experiment_analysis(analysis.pk)
        self.assertFalse(outcome['success'])
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, ExperimentAnalysis.STATUS_ERROR)
        self.assertIn('کلید API', analysis.error_message)

    def test_invalid_ai_response_marks_error(self):
        analysis = self._analysis()
        with mock.patch('apps.ai_assistant.providers.gemini.GeminiProvider.generate', return_value='not json'):
            outcome = run_experiment_analysis(analysis.pk)
        self.assertFalse(outcome['success'])
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, ExperimentAnalysis.STATUS_ERROR)

    def test_unexpected_exception_marks_error(self):
        analysis = self._analysis()
        with mock.patch(
            'apps.ai_assistant.providers.gemini.GeminiProvider.generate',
            side_effect=RuntimeError('unexpected'),
        ):
            outcome = run_experiment_analysis(analysis.pk)
        self.assertFalse(outcome['success'])
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, ExperimentAnalysis.STATUS_ERROR)

    def test_provider_failure_marks_error(self):
        analysis = self._analysis()
        with mock.patch(
            'apps.ai_assistant.providers.gemini.GeminiProvider.generate',
            side_effect=ProviderError('boom'),
        ):
            run_experiment_analysis(analysis.pk)
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, ExperimentAnalysis.STATUS_ERROR)
        self.assertEqual(analysis.error_message, 'boom')


@override_settings(AI_ASSISTANT_CONFIG=AI_CONFIG, MEDIA_ROOT=TEMP_MEDIA_ROOT)
class AnalysisViewTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username='sup', password='pw12345!', role='supervisor')
        self.client.force_login(self.user)
        self.experiment = Experiment.objects.create(
            name='آزمایش', date=datetime.date(2025, 8, 1),
            soil_file=SimpleUploadedFile('soil.txt', b'x'),
            leaf_file=SimpleUploadedFile('leaf.txt', b'x'),
            water_file=SimpleUploadedFile('water.txt', b'x'),
        )

    def _grant(self, *codenames):
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))

    def test_analyze_forbidden_without_permission(self):
        self.assertEqual(self.client.get(reverse('ai_assistant:analyze')).status_code, 403)

    def test_analyze_queues_task_with_main_provider(self):
        self._grant('add_experimentanalysis', 'view_experimentanalysis')
        with mock.patch('apps.ai_assistant.views.analyze_experiment.delay') as queued:
            response = self.client.post(reverse('ai_assistant:analyze'), {'experiment': self.experiment.pk})
        analysis = ExperimentAnalysis.objects.get()
        self.assertRedirects(response, reverse('ai_assistant:analysis_detail', args=[analysis.pk]))
        self.assertEqual(analysis.provider, 'gemini')
        self.assertEqual(analysis.requested_by, self.user)
        queued.assert_called_once_with(analysis.pk)

    def test_analyze_rejects_unconfigured_provider(self):
        self._grant('add_experimentanalysis')
        with mock.patch('apps.ai_assistant.views.analyze_experiment.delay') as queued:
            response = self.client.post(
                reverse('ai_assistant:analyze'),
                {'experiment': self.experiment.pk, 'provider': 'chatgpt'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExperimentAnalysis.objects.exists())
        queued.assert_not_called()

    def test_status_endpoint(self):
        self._grant('view_experimentanalysis')
        analysis = ExperimentAnalysis.objects.create(experiment=self.experiment, provider='gemini')
        response = self.client.get(reverse('ai_assistant:analysis_status', args=[analysis.pk]))
        self.assertEqual(response.json(), {'status': 'pending', 'finished': False})

    def test_detail_renders_result(self):
        self._grant('view_experimentanalysis')
        analysis = ExperimentAnalysis.objects.create(
            experiment=self.experiment, provider='gemini', status=ExperimentAnalysis.STATUS_DONE,
            summary='خلاصه تست', result={'irrigation': ['آبیاری عمیق']},
        )
        response = self.client.get(reverse('ai_assistant:analysis_detail', args=[analysis.pk]))
        self.assertContains(response, 'خلاصه تست')
        self.assertContains(response, 'آبیاری عمیق')

    def test_settings_page_renders(self):
        self._grant('change_aisettings')
        response = self.client.get(reverse('public:settings'))
        self.assertContains(response, 'تنظیمات هوش مصنوعی')

    def test_legacy_settings_url_redirects(self):
        self._grant('change_aisettings')
        response = self.client.get(reverse('ai_assistant:settings'))
        self.assertRedirects(response, reverse('public:settings'), fetch_redirect_response=False)

    def test_settings_update_main_provider(self):
        self._grant('change_aisettings')
        response = self.client.post(reverse('ai_assistant:main_provider'), {'main_provider': 'claude'})
        self.assertRedirects(response, reverse('public:settings'), fetch_redirect_response=False)
        self.assertEqual(AISettings.get_solo().main_provider, 'claude')

    def test_settings_reject_unconfigured_provider(self):
        self._grant('change_aisettings')
        self.client.post(reverse('ai_assistant:main_provider'), {'main_provider': 'chatgpt'})
        self.assertEqual(AISettings.get_solo().main_provider, '')

    def test_define_custom_provider_and_use_as_main(self):
        self._grant('change_aisettings')
        response = self.client.post(reverse('ai_assistant:provider_create'), {
            'key': 'My-LLM', 'label': 'سرویس من', 'provider_type': 'chatgpt',
            'api_key': 'secret', 'model': 'm1', 'base_url': 'https://llm.example.com/v1', 'is_active': 'on',
        })
        self.assertRedirects(response, reverse('public:settings'), fetch_redirect_response=False)
        row = AIProviderConfig.objects.get()
        self.assertEqual(row.key, 'my-llm')
        self.client.post(reverse('ai_assistant:main_provider'), {'main_provider': 'my-llm'})
        self.assertEqual(get_main_provider_name(), 'my-llm')

    def test_edit_provider_keeps_key_when_blank(self):
        self._grant('change_aisettings')
        row = AIProviderConfig.objects.create(key='grok', label='Grok', provider_type='grok', api_key='old', model='a')
        self.client.post(reverse('ai_assistant:provider_update', args=[row.pk]), {
            'label': 'Grok', 'api_key': '', 'model': 'b', 'base_url': '', 'is_active': 'on',
        })
        row.refresh_from_db()
        self.assertEqual(row.api_key, 'old')
        self.assertEqual(row.model, 'b')

    def test_builtin_key_requires_matching_type(self):
        self._grant('change_aisettings')
        response = self.client.post(reverse('ai_assistant:provider_create'), {
            'key': 'claude', 'label': 'x', 'provider_type': 'grok', 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AIProviderConfig.objects.exists())

    def test_provider_management_forbidden_without_permission(self):
        self.assertEqual(self.client.get(reverse('ai_assistant:provider_create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('public:settings')).status_code, 403)


class ReportBuilderTests(SimpleTestCase):

    def test_build_experiment_report(self):
        result = {
            'urgency': 'critical',
            'soil': {'status': 'شور', 'findings': ['EC بالا'], 'issues': ['شوری']},
            'irrigation': ['آبیاری عمیق'],
            'fertilization': [{'name': 'اوره', 'dose': '10'}],
            'follow_up': ['آزمایش مجدد'],
        }
        sections, priority = build_experiment_report(result)
        by_key = {s['key']: s['items'] for s in sections}
        self.assertEqual(priority, 'high')
        self.assertIn('خاک - شوری', by_key['warnings'])
        self.assertIn('آبیاری: آبیاری عمیق', by_key['recommendations'])
        self.assertIn('کوددهی: نام: اوره، مقدار: 10', by_key['recommendations'])
        self.assertEqual(by_key['prevention'], ['آزمایش مجدد'])

    def test_build_leaf_report_priority_from_urgency(self):
        analysis = mock.Mock(
            diseases=['لکه'], deficiencies=[], pests=[], urgency='High', treatment_time='صبح',
            recommendations=['سم'], prevention=['تهویه'], health_score=70,
        )
        sections, priority = build_leaf_report(analysis)
        self.assertEqual(priority, 'high')
        by_key = {s['key']: s['items'] for s in sections}
        self.assertEqual(by_key['findings'], ['بیماری: لکه'])
        self.assertEqual(by_key['prevention'], ['تهویه'])
