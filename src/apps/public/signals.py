import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_q.tasks import async_task

from . import models

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

    if status == 'start':
        models.Run.objects.filter(pk=instance.run_id).update(status='open')
        return

    if status != 'end':
        return

    models.Run.objects.filter(pk=instance.run_id).update(status='closed')

    # Re-fetch run with relations for optimality / discharge report check
    try:
        run = models.Run.objects.select_related(
            'outlet__plot__zone__farm', 'created_by'
        ).get(pk=instance.run_id)
    except models.Run.DoesNotExist:
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


def _schedule_weather_fetch(run_status_id):
    try:
        async_task('apps.public.tasks.fetch_weather_for_run_status', run_status_id)
    except Exception as exc:
        logger.error('Failed to queue weather fetch for RunStatus %s: %s', run_status_id, exc)
