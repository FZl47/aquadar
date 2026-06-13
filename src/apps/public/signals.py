from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from django_q.tasks import async_task

from . import models


@receiver(post_save, sender=models.RunStatus)
def run_status_create(sender, instance, created, **kwargs):
    with transaction.atomic():
        if not created:
            return

        # Schedule weather fetch if GPS is available
        if instance.gps_lat is not None and instance.gps_lng is not None:
            transaction.on_commit(lambda: _schedule_weather_fetch(instance.id))

        status = instance.status
        if status != 'end':
            return

        # Check irrigation run is optimal
        if (instance.run.is_irrigation_optimal is True) or (instance.run.is_irrigation_optimal is None):
            return

        # Irrigation run is not optimal - create report if configured
        settings_obj = models.RunSettings.objects.first()
        if settings_obj and settings_obj.create_report_to_supervisor_if_has_problem:
            instance.run.report_irrigation_bad()


def _schedule_weather_fetch(run_status_id):
    try:
        async_task('apps.public.tasks.fetch_weather_for_run_status', run_status_id)
    except Exception:
        pass
