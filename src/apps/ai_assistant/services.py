import io
import json
import logging

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from google import genai
from google.genai import types
from PIL import Image

from apps.public.reports import create_system_report, resolve_recipients

from .attachments import load_experiment_attachments
from .models import AISettings, ExperimentAnalysis
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .providers.base import ProviderError
from .providers.registry import get_default_provider_name, get_provider, get_provider_labels
from .reports import build_experiment_report

logger = logging.getLogger(__name__)

VALID_URGENCIES = ('low', 'medium', 'high', 'critical')


def get_main_provider_name():
    configured = AISettings.get_solo().main_provider
    if configured and configured in get_provider_labels():
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
    system_report = create_experiment_system_report(analysis, result, urgency)
    return {'success': True, 'system_report_id': system_report.pk if system_report else None}


def create_experiment_system_report(analysis, result, urgency):
    recipients = resolve_recipients(extra=[analysis.requested_by])
    if not recipients:
        return None
    sections, priority = build_experiment_report(result)
    experiment = analysis.experiment
    system_report = create_system_report(
        category='experiment_analysis',
        title=f'گزارش تحلیل آزمایش {experiment.name}',
        summary=str(result.get('summary', '')),
        sections=sections,
        priority=priority,
        recipients=recipients,
        subject=experiment.name,
        link=reverse('ai_assistant:analysis_detail', args=[analysis.pk]),
    )
    ExperimentAnalysis.objects.filter(pk=analysis.pk).update(final_report=system_report.final_report)
    return system_report


GEMINI_MODEL = 'gemini-2.5-flash'


def _strip_json_fences(text):
    text = text.strip()
    if text.startswith('```'):
        parts = text.split('```')
        text = parts[1] if len(parts) > 1 else text.strip('`')
        if text.startswith('json'):
            text = text[4:]
    return text.strip()


def _gemini_client():
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        logger.error('GEMINI_API_KEY not configured')
        return None
    return genai.Client(api_key=api_key)


def _image_to_part(image_path, max_dim=1600, jpeg_quality=85):
    try:
        img = Image.open(image_path)
    except Exception as exc:
        raise ValueError(f'Cannot open image {image_path}: {exc}') from exc
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    img.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=jpeg_quality, optimize=True)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type='image/jpeg')


def analyze_plot_leaf(image_path):
    client = _gemini_client()
    if client is None:
        return {}

    prompt = (
        'You are an expert agricultural analyst specializing in pistachio trees. '
        'Analyze this leaf image and respond ONLY with valid JSON in this exact format:\n'
        '{\n'
        '  "health_score": <integer 0-100>,\n'
        '  "diseases": [<list of disease names in Persian>],\n'
        '  "deficiencies": [<list of nutrient deficiencies in Persian>],\n'
        '  "pests": [<list of pest names in Persian>],\n'
        '  "recommendations": [<list of treatment recommendations in Persian>],\n'
        '  "prevention": [<list of prevention measures in Persian>],\n'
        '  "urgency": "<low|medium|high|critical>",\n'
        '  "treatment_time": "<timeframe in Persian>",\n'
        '  "summary": "<brief overall assessment in Persian>"\n'
        '}'
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, _image_to_part(image_path)],
        )
    except Exception as exc:
        logger.error('Gemini API call failed: %s', exc)
        return {}
    try:
        return json.loads(_strip_json_fences(response.text))
    except json.JSONDecodeError as exc:
        logger.error('Gemini response not valid JSON: %s | raw: %.200s', exc, response.text)
        return {}
