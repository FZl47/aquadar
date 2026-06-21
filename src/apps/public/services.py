import io
import json
import logging

import requests
from google import genai
from google.genai import types
from PIL import Image

from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_MODEL = 'gemini-2.5-flash'

_OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
_WEATHER_CURRENT_VARS = (
    'temperature_2m,relative_humidity_2m,wind_speed_10m,'
    'precipitation,shortwave_radiation,uv_index,cloud_cover'
)


def fetch_weather_data(lat, lng):
    """Call Open-Meteo API and return raw current-weather dict, or None on failure."""
    try:
        resp = requests.get(
            _OPEN_METEO_URL,
            params={
                'latitude': float(lat),
                'longitude': float(lng),
                'current': _WEATHER_CURRENT_VARS,
                'wind_speed_unit': 'ms',
                'forecast_days': 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get('current', {})
        if not data:
            logger.warning('Open-Meteo returned empty current block (lat=%s lng=%s)', lat, lng)
        return data
    except Exception as exc:
        logger.error('Open-Meteo fetch failed (lat=%s lng=%s): %s', lat, lng, exc)
        return None


def save_plot_weather(plot, weather_data, source='scheduled'):
    """Persist a PlotWeather record from a raw Open-Meteo current-weather dict.

    Returns the saved PlotWeather instance or None if creation failed.
    """
    from .models import PlotWeather

    def _d(v, places=2):
        return round(float(v), places) if v is not None else None

    try:
        pw = PlotWeather.objects.create(
            plot=plot,
            temperature_c=_d(weather_data.get('temperature_2m')),
            humidity=int(weather_data['relative_humidity_2m']) if weather_data.get('relative_humidity_2m') is not None else None,
            wind_speed=_d(weather_data.get('wind_speed_10m')),
            precipitation=_d(weather_data.get('precipitation')),
            solar_radiation=_d(weather_data.get('shortwave_radiation')),
            uv_index=_d(weather_data.get('uv_index'), 1),
            cloud_cover=int(weather_data['cloud_cover']) if weather_data.get('cloud_cover') is not None else None,
            source=source,
        )
        logger.info(
            'PlotWeather %s saved for plot %s (source=%s): temp=%s, precip=%s, solar=%s, uv=%s, cloud=%s',
            pw.id, plot.id, source,
            pw.temperature_c, pw.precipitation, pw.solar_radiation, pw.uv_index, pw.cloud_cover,
        )
        return pw
    except Exception as exc:
        logger.error('Failed to save PlotWeather for plot %s: %s', plot.id, exc)
        return None


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
