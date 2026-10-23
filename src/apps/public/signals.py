import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.urls import reverse_lazy

from apps.notification.utils import absolute_url, create_user_notif

from . import models
from .reports import jalali_now, operation_recipients, user_display_name
from .tasks import fetch_weather_for_run_status

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=models.Experiment)
def experiment_delete_files(sender, instance, **kwargs):
    for field in instance.FILE_FIELDS:
        stored = getattr(instance, field)
        if stored:
            stored.delete(save=False)


@receiver(post_save, sender=models.RunStatus)
def run_status_create(sender, instance, created, **kwargs):
    if not created:
        return

    # Schedule weather fetch if GPS is available (after commit so worker sees the row).
    if instance.gps_lat is not None and instance.gps_lng is not None:
        run_status_id = instance.id
        transaction.on_commit(lambda: _schedule_weather_fetch(run_status_id))

    status = instance.status

    if status not in ('start', 'end'):
        return

    models.Run.objects.filter(pk=instance.run_id).update(status='open' if status == 'start' else 'closed')

    try:
        run = models.Run.objects.select_related(
            'outlet__plot__zone__farm', 'created_by'
        ).get(pk=instance.run_id)
    except models.Run.DoesNotExist:
        return

    plot = run.outlet.plot
    farm = plot.zone.farm
    lines = [f'ردیف {run.outlet.number}', f'آبیار: {user_display_name(run.created_by)}']
    if status == 'start':
        event, label = 'irrigation_started', 'شروع آبیاری'
    else:
        event, label = 'irrigation_finished', 'پایان آبیاری'
        if run.duration_seconds:
            lines.append(f'مدت: {round(run.duration_seconds / 60, 1)} دقیقه')
    title = f'{label}: {farm.name} / {plot.name}'
    for user in operation_recipients(farm, run.created_by):
        create_user_notif(
            user, 'operation_event', title, '\n'.join([title, *lines]),
            kwargs_notif={
                'event': event,
                'event_label': label,
                'user': user_display_name(run.created_by),
                'farm': farm.name,
                'plot': plot.name,
                'details': '، '.join(lines),
                'time': jalali_now(),
                'link': absolute_url(plot.get_absolute_url()),
            },
        )
    if status == 'start':
        return

    # None = cannot evaluate (no avg duration / settings); True = optimal → no report
    optimal = run.is_irrigation_optimal
    if optimal is True or optimal is None:
        return

    # Suboptimal (high or low water discharge) — create system report if configured
    settings_obj = models.RunSettings.objects.first()
    if settings_obj is None or not settings_obj.create_report_to_supervisor_if_has_problem:
        return

    try:
        sr = run.report_irrigation_bad()
        if sr is None:
            logger.warning(
                'High/low discharge report not created for run %s (no supervisors/admins)',
                run.id,
            )
        else:
            logger.info('High/low discharge SystemReport %s created for run %s', sr.id, run.id)
    except Exception as exc:
        logger.exception('Failed to create high/low discharge report for run %s: %s', run.id, exc)


def _record_lines(instance):
    lines = [f'ثبت‌کننده: {user_display_name(instance.created_by)}']
    if instance.category_id:
        lines.append(f'نوع: {instance.category}')
    lines.append(f'عنوان: {instance.title}')
    if instance.quantity is not None:
        lines.append(f'مقدار: {instance.quantity_display}')
    return lines


@receiver(post_save, sender=models.FertilizationRecord)
def fertilization_created(sender, instance, created, **kwargs):
    if not created:
        return
    plot = instance.plot
    farm = plot.zone.farm
    lines = _record_lines(instance)
    title = f'ثبت کوددهی: {farm.name} / {plot.name}'
    for user in operation_recipients(farm, instance.created_by):
        create_user_notif(
            user, 'operation_event', title, '\n'.join([title, *lines]),
            kwargs_notif={
                'event': 'fertilization_registered',
                'event_label': 'ثبت کوددهی',
                'user': user_display_name(instance.created_by),
                'farm': farm.name,
                'plot': plot.name,
                'details': '، '.join(lines),
                'time': jalali_now(),
                'link': absolute_url(plot.get_absolute_url()),
            },
        )


@receiver(post_save, sender=models.ReportFoliarSpray)
def foliar_spray_created(sender, instance, created, **kwargs):
    if not created:
        return
    plot = instance.plot
    farm = plot.zone.farm
    lines = _record_lines(instance)
    title = f'ثبت سم‌پاشی و محلول‌پاشی: {farm.name} / {plot.name}'
    for user in operation_recipients(farm, instance.created_by):
        create_user_notif(
            user, 'operation_event', title, '\n'.join([title, *lines]),
            kwargs_notif={
                'event': 'foliar_spray_registered',
                'event_label': 'ثبت سم‌پاشی و محلول‌پاشی',
                'user': user_display_name(instance.created_by),
                'farm': farm.name,
                'plot': plot.name,
                'details': '، '.join(lines),
                'time': jalali_now(),
                'link': absolute_url(plot.get_absolute_url()),
            },
        )


@receiver(post_save, sender=models.Experiment)
def experiment_created(sender, instance, created, **kwargs):
    if not created:
        return
    lines = [f'نام آزمایش: {instance.name}', f'ثبت‌کننده: {user_display_name(instance.created_by)}']
    title = 'ثبت آزمایش جدید'
    for user in operation_recipients(actor=instance.created_by):
        create_user_notif(
            user, 'operation_event', title, '\n'.join([title, *lines]),
            kwargs_notif={
                'event': 'experiment_created',
                'event_label': title,
                'user': user_display_name(instance.created_by),
                'farm': '',
                'plot': '',
                'details': '، '.join(lines),
                'time': jalali_now(),
                'link': absolute_url(reverse_lazy('public:experiment_detail', args=[instance.pk])),
            },
        )


def _schedule_weather_fetch(run_status_id):
    try:
        fetch_weather_for_run_status.delay(run_status_id)
    except Exception as exc:
        logger.error('Failed to queue weather fetch for RunStatus %s: %s', run_status_id, exc)
