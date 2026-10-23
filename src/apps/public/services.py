import logging

import requests

logger = logging.getLogger(__name__)

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
