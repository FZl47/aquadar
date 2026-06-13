import logging

import requests
from django_q.tasks import async_task

from .models import RunStatus

logger = logging.getLogger(__name__)


def fetch_weather_for_run_status(run_status_id):
    try:
        run_status = RunStatus.objects.get(id=run_status_id)
    except RunStatus.DoesNotExist:
        return

    if run_status.weather_fetched:
        return

    if run_status.gps_lat is None or run_status.gps_lng is None:
        return

    try:
        url = 'https://api.open-meteo.com/v1/forecast'
        params = {
            'latitude': float(run_status.gps_lat),
            'longitude': float(run_status.gps_lng),
            'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m',
            'wind_speed_unit': 'ms',
            'forecast_days': 1,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        current = data.get('current', {})
        temp = current.get('temperature_2m')
        wind = current.get('wind_speed_10m')
        humidity = current.get('relative_humidity_2m')

        update_fields = ['weather_fetched']
        run_status.weather_fetched = True

        if temp is not None:
            run_status.temperature_c = round(temp, 2)
            update_fields.append('temperature_c')
        if wind is not None:
            run_status.wind_speed = round(wind, 2)
            update_fields.append('wind_speed')
        if humidity is not None:
            run_status.humidity = int(humidity)
            update_fields.append('humidity')

        run_status.save(update_fields=update_fields)
        logger.info('Weather fetched for RunStatus %s: temp=%s, wind=%s, humidity=%s', run_status_id, temp, wind, humidity)

    except Exception as exc:
        logger.error('Weather fetch failed for RunStatus %s: %s', run_status_id, exc)


def retry_failed_weather_fetches():
    pending = RunStatus.objects.filter(
        gps_lat__isnull=False,
        gps_lng__isnull=False,
        weather_fetched=False,
    ).values_list('id', flat=True)

    count = 0
    for rs_id in pending:
        async_task('apps.public.tasks.fetch_weather_for_run_status', rs_id)
        count += 1

    logger.info('Scheduled weather retry for %d RunStatus records', count)
    return count
