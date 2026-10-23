import json
import logging

from django.utils import timezone

from .attachments import load_experiment_attachments
from .models import AISettings, ExperimentAnalysis
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .providers.base import ProviderError
from .providers.registry import PROVIDER_CLASSES, get_default_provider_name, get_provider

logger = logging.getLogger(__name__)

VALID_URGENCIES = ('low', 'medium', 'high', 'critical')


def get_main_provider_name():
    configured = AISettings.get_solo().main_provider
    if configured in PROVIDER_CLASSES:
        return configured
    return get_default_provider_name()


def parse_json_response(text):
    cleaned = (text or '').strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.strip('`')
        if cleaned.lower().startswith('json'):
            cleaned = cleaned[4:]
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end <= start:
        raise ValueError('JSON not found in AI response')
    return json.loads(cleaned[start:end + 1])


def run_experiment_analysis(analysis_id):
    analysis = ExperimentAnalysis.objects.select_related('experiment').filter(pk=analysis_id).first()
    if analysis is None:
        return {'success': False, 'error': 'analysis not found'}

    ExperimentAnalysis.objects.filter(pk=analysis.pk).update(status=ExperimentAnalysis.STATUS_ANALYZING)

    provider = None
    try:
        provider = get_provider(analysis.provider)
        if not provider.is_configured:
            raise ProviderError(f'کلید API برای {provider.label} تنظیم نشده است')
        attachments = load_experiment_attachments(analysis.experiment)
        raw = provider.generate(SYSTEM_PROMPT, build_user_prompt(analysis.experiment), attachments)
        result = parse_json_response(raw)
    except Exception as exc:
        logger.exception('Experiment analysis %s failed: %s', analysis_id, exc)
        ExperimentAnalysis.objects.filter(pk=analysis.pk).update(
            status=ExperimentAnalysis.STATUS_ERROR,
            error_message=str(exc)[:2000],
            model_name=provider.model if provider else '',
        )
        return {'success': False, 'error': str(exc)}

    urgency = result.get('urgency') if result.get('urgency') in VALID_URGENCIES else ''
    ExperimentAnalysis.objects.filter(pk=analysis.pk).update(
        status=ExperimentAnalysis.STATUS_DONE,
        model_name=provider.model,
        urgency=urgency,
        summary=str(result.get('summary', '')),
        result=result,
        raw_response=raw,
        error_message='',
        analyzed_at=timezone.now(),
    )
    return {'success': True}
