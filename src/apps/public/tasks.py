import json
import logging
from datetime import timedelta

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.translation import gettext as _

from .gee import analyze_plot_condition, compute_vegetation_indices
from .models import Plot, PlotAIReport, PlotVegetationIndex, PlotWeather, Run, RunStatus
from .reports import (
    build_plot_report, create_system_report, min_health_score, resolve_recipients,
)
from .services import fetch_weather_data, save_plot_weather

logger = logging.getLogger(__name__)

_WEATHER_RETRY_WINDOW_HOURS = 3
_WEATHER_RETRY_MAX = 100


@shared_task
def fetch_weather_for_run_status(run_status_id):
    try:
        run_status = RunStatus.objects.get(id=run_status_id)
    except RunStatus.DoesNotExist:
        return

    if run_status.weather_fetched:
        return

    lat = run_status.gps_lat
    lng = run_status.gps_lng
    if lat is None or lng is None:
        try:
            plot = run_status.run.outlet.plot
            lat = plot.gps_lat
            lng = plot.gps_lng
        except Exception:
            pass
    if lat is None or lng is None:
        return

    weather = fetch_weather_data(lat, lng)
    if weather is None:
        logger.error('Weather fetch returned None for RunStatus %s', run_status_id)
        return

    temp = weather.get('temperature_2m')
    wind = weather.get('wind_speed_10m')
    humidity = weather.get('relative_humidity_2m')
    precipitation = weather.get('precipitation')
    solar_radiation = weather.get('shortwave_radiation')
    uv_index = weather.get('uv_index')
    cloud_cover = weather.get('cloud_cover')

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
    if precipitation is not None:
        run_status.precipitation = round(precipitation, 2)
        update_fields.append('precipitation')
    if solar_radiation is not None:
        run_status.solar_radiation = round(solar_radiation, 2)
        update_fields.append('solar_radiation')
    if uv_index is not None:
        run_status.uv_index = round(uv_index, 1)
        update_fields.append('uv_index')
    if cloud_cover is not None:
        run_status.cloud_cover = int(cloud_cover)
        update_fields.append('cloud_cover')

    run_status.save(update_fields=update_fields)
    logger.info(
        'Weather saved for RunStatus %s: temp=%s, wind=%s, humidity=%s, precip=%s, solar=%s, uv=%s, cloud=%s',
        run_status_id, temp, wind, humidity, precipitation, solar_radiation, uv_index, cloud_cover,
    )


@shared_task
def retry_failed_weather_fetches():
    cutoff = timezone.now() - timedelta(hours=_WEATHER_RETRY_WINDOW_HOURS)
    pending = RunStatus.objects.filter(
        gps_lat__isnull=False,
        gps_lng__isnull=False,
        weather_fetched=False,
        created_at__gte=cutoff,
    ).values_list('id', flat=True)[:_WEATHER_RETRY_MAX]

    count = 0
    for rs_id in pending:
        fetch_weather_for_run_status.delay(rs_id)
        count += 1

    logger.info('Scheduled weather retry for %d recent RunStatus records', count)
    return count


def _ai_report_has_problem(ai_report):
    threshold = min_health_score()
    if ai_report.health_score is not None and ai_report.health_score < threshold:
        return True
    for risk in ai_report.risks or []:
        if isinstance(risk, dict) and risk.get('severity') == 'high':
            return True
    return False


@shared_task
def fetch_vegetation_indices(plot_id):
    try:
        plot = Plot.objects.get(id=plot_id)
    except Plot.DoesNotExist:
        return

    data = compute_vegetation_indices(plot)
    if not data:
        logger.warning('No vegetation indices computed for plot %s', plot_id)
        return

    vi = PlotVegetationIndex.objects.create(
        plot=plot,
        ndvi=data.get('ndvi_mean'),
        ndmi=data.get('ndmi_mean'),
        ndre=data.get('ndre_mean'),
        evi=data.get('evi_mean'),
        savi=data.get('savi_mean'),
        msavi=data.get('msavi_mean'),
        source=data.get('source', ''),
        image_id=data.get('image_id', '') or '',
        pixel_count=data.get('pixel_count'),
        observed_at=data.get('observed_at'),
    )

    image_png = data.get('image_png')
    if image_png:
        vi.image.save(f'ndvi_{plot_id}_{vi.id}.png', ContentFile(image_png), save=True)

    satellite_image_png = data.get('satellite_image_png')
    if satellite_image_png:
        vi.satellite_image.save(f'satellite_{plot_id}_{vi.id}.png', ContentFile(satellite_image_png), save=True)

    moisture_image_png = data.get('moisture_image_png')
    if moisture_image_png:
        vi.moisture_image.save(f'ndmi_{plot_id}_{vi.id}.png', ContentFile(moisture_image_png), save=True)

    logger.info('Vegetation indices stored for plot %s (VI %s)', plot_id, vi.id)
    return vi.id


def _irrigation_text(moisture_score):
    if moisture_score is None:
        return ''
    if moisture_score < 30:
        return _('High water need; increase irrigation.')
    if moisture_score < 50:
        return _('Moderate moisture; monitor irrigation schedule.')
    return _('Soil moisture condition is adequate.')


def _create_plot_system_report(plot, ai_report, result):
    recipients = resolve_recipients(plot.zone.farm)
    if not recipients:
        logger.warning('No recipients for plot %s analysis report', plot.id)
        return None
    sections, priority = build_plot_report(plot, ai_report, result)
    system_report = create_system_report(
        category='plot_analysis',
        title=f'گزارش تحلیل زمین {plot.name}',
        summary=ai_report.summary,
        sections=sections,
        priority=priority,
        recipients=recipients,
        subject=f'{plot.zone.farm.name} / {plot.zone.name} / {plot.name}',
        score=ai_report.health_score,
        plot=plot,
        link=str(plot.get_absolute_url()),
    )
    PlotAIReport.objects.filter(pk=ai_report.pk).update(final_report=system_report.final_report)
    ai_report.final_report = system_report.final_report
    return system_report


def generate_plot_report(plot_id):
    """Build a PlotAIReport from a rule-based analysis and alert supervisors on problems."""
    try:
        plot = Plot.objects.select_related('zone__farm').get(id=plot_id)
    except Plot.DoesNotExist:
        return None

    result = analyze_plot_condition(plot)

    greenness = result.get('greenness_score')
    moisture = result.get('moisture_score')
    water_m3 = result.get('water_m3')
    ai_report = PlotAIReport.objects.create(
        plot=plot,
        health_score=result.get('health_score'),
        summary=result.get('summary', ''),
        soil_assessment=(
            _('Greenness: %(green)s%% | Moisture: %(moist)s%%') % {
                'green': greenness if greenness is not None else '-',
                'moist': moisture if moisture is not None else '-',
            }
        ),
        irrigation_assessment=_irrigation_text(moisture),
        pest_risk='',
        leaf_summary='',
        season_recommendations=result.get('suggestions', []),
        risks=result.get('problems', []),
        data_sources={
            'vegetation': result.get('ndvi') is not None,
            'weather': bool(result.get('weather')),
            'water': water_m3 is not None,
        },
        raw_response=json.dumps(result, ensure_ascii=False),
    )

    has_problem = _ai_report_has_problem(ai_report)
    system_report = _create_plot_system_report(plot, ai_report, result)

    return {
        'success': True,
        'report_id': ai_report.id,
        'plot_id': plot.id,
        'plot_name': plot.name,
        'has_problem': has_problem,
        'system_report_id': system_report.id if system_report else None,
        'final_report': ai_report.final_report,
        'health_score': result.get('health_score'),
        'greenness_score': greenness,
        'moisture_score': moisture,
        'water_m3': water_m3,
        'ndvi': result.get('ndvi'),
        'ndmi': result.get('ndmi'),
        'ndre': result.get('ndre'),
        'evi': result.get('evi'),
        'savi': result.get('savi'),
        'msavi': result.get('msavi'),
        'summary': result.get('summary', ''),
        'problems': result.get('problems', []),
        'suggestions': result.get('suggestions', []),
        'weather': result.get('weather', {}),
        'observed_at': result.get('observed_at'),
        'has_data': result.get('has_data', False),
    }


@shared_task
def analyze_plot(plot_id):
    """Full pipeline: refresh Sentinel-2 indices, then run the rule-based report."""
    try:
        fetch_vegetation_indices(plot_id)
    except Exception as exc:
        logger.error('Vegetation index refresh failed for plot %s: %s', plot_id, exc)
    return generate_plot_report(plot_id)


@shared_task
def analyze_all_plots(farm_id=None):
    """Queue full analysis (vegetation indices + health report) for every plot."""
    plots = Plot.objects.select_related('zone').all()
    if farm_id:
        plots = plots.filter(zone__farm_id=farm_id)

    count = 0
    for pid in plots.values_list('id', flat=True):
        try:
            analyze_plot.delay(pid)
            count += 1
        except Exception as exc:
            logger.error('Failed to queue analyze_plot for plot %s: %s', pid, exc)

    logger.info('Scheduled analysis for %d plots', count)
    return count


@shared_task
def fetch_weather_for_plot(plot_id, source='scheduled'):
    """Fetch current weather for a plot via its GPS/boundary and save a PlotWeather record.

    Returns serialisable dict on success, None on failure.
    """
    try:
        plot = Plot.objects.select_related('zone__farm').get(id=plot_id)
    except Plot.DoesNotExist:
        return None

    lat, lng = plot.resolve_gps()
    if lat is None or lng is None:
        logger.warning('Plot %s has no GPS/boundary; skipping weather fetch', plot_id)
        return None

    # Persist resolved centroid so future scheduled runs do not re-parse boundary.
    if plot.gps_lat is None or plot.gps_lng is None:
        Plot.objects.filter(pk=plot.pk).update(gps_lat=lat, gps_lng=lng)

    weather = fetch_weather_data(lat, lng)
    if weather is None:
        return None

    pw = save_plot_weather(plot, weather, source=source)
    if pw is None:
        return None

    return {
        'id': pw.id,
        'temperature_c': float(pw.temperature_c) if pw.temperature_c is not None else None,
        'humidity': pw.humidity,
        'wind_speed': float(pw.wind_speed) if pw.wind_speed is not None else None,
        'precipitation': float(pw.precipitation) if pw.precipitation is not None else None,
        'solar_radiation': float(pw.solar_radiation) if pw.solar_radiation is not None else None,
        'uv_index': float(pw.uv_index) if pw.uv_index is not None else None,
        'cloud_cover': pw.cloud_cover,
        'fetched_at': pw.created_at.isoformat(),
    }


@shared_task
def fetch_weather_all_plots():
    """Queue a weather fetch for every plot that has GPS or a boundary. Runs daily at 18:00."""
    plot_ids = set(
        Plot.objects.filter(gps_lat__isnull=False, gps_lng__isnull=False).values_list('id', flat=True)
    )
    for pid, boundary in Plot.objects.values_list('id', 'boundary'):
        if boundary:
            plot_ids.add(pid)

    count = 0
    for pid in plot_ids:
        try:
            fetch_weather_for_plot.delay(pid, 'scheduled')
            count += 1
        except Exception as exc:
            logger.error('Failed to queue weather fetch for plot %s: %s', pid, exc)
    logger.info('Scheduled daily weather fetch for %d plots', count)
    return count


@shared_task
def fetch_vegetation_all_plots(farm_id=None):
    """Queue vegetation index (NDVI/NDMI) fetch for all plots. Used by periodic schedule."""
    plots = Plot.objects.all()
    if farm_id:
        plots = plots.filter(zone__farm_id=farm_id)

    count = 0
    for pid in plots.values_list('id', flat=True):
        fetch_vegetation_indices.delay(pid)
        count += 1
    logger.info('Scheduled vegetation index fetch for %d plots', count)
    return count
