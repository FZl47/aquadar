import logging
import sys

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


class PublicConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.public'

    def ready(self):
        from . import signals  # noqa: F401
        post_migrate.connect(_setup_periodic_tasks, sender=self)

        # Repair/create schedules when the process starts (runserver / qcluster),
        # but not during migrate/makemigrations (tables may not exist yet).
        if not any(cmd in sys.argv for cmd in ('migrate', 'makemigrations', 'check')):
            try:
                _setup_periodic_tasks(sender=self)
            except Exception as exc:
                logger.debug('Periodic task setup deferred/skipped: %s', exc)


def _ensure_schedule(func, name, schedule_type, *, cron=None, minutes=None):
    """Create or repair a django-q Schedule so overdue jobs run again."""
    from django_q.models import Schedule
    from django_q.tasks import schedule as q_schedule
    from django.utils import timezone

    sched = Schedule.objects.filter(func=func).first()
    now = timezone.now()

    if sched is None:
        kwargs = {
            'func': func,
            'schedule_type': schedule_type,
            'name': name,
            'repeats': -1,
        }
        if cron is not None:
            kwargs['cron'] = cron
        if minutes is not None:
            kwargs['minutes'] = minutes
        q_schedule(**kwargs)
        logger.info('Created django-q schedule %s', name)
        return

    update_fields = []
    if sched.name != name:
        sched.name = name
        update_fields.append('name')
    if sched.schedule_type != schedule_type:
        sched.schedule_type = schedule_type
        update_fields.append('schedule_type')
    if cron is not None and sched.cron != cron:
        sched.cron = cron
        update_fields.append('cron')
    if minutes is not None and sched.minutes != minutes:
        sched.minutes = minutes
        update_fields.append('minutes')
    if sched.repeats == 0:
        sched.repeats = -1
        update_fields.append('repeats')
    # Catch up schedules stuck in the past so the cluster picks them up promptly.
    if sched.next_run is None or sched.next_run < now:
        sched.next_run = now
        update_fields.append('next_run')
    if update_fields:
        sched.save(update_fields=update_fields)
        logger.info('Repaired django-q schedule %s fields=%s', name, update_fields)


def _setup_periodic_tasks(sender, **kwargs):
    try:
        from django_q.models import Schedule

        _ensure_schedule(
            'apps.public.tasks.retry_failed_weather_fetches',
            'retry_weather_fetch',
            Schedule.HOURLY,
        )
        _ensure_schedule(
            'apps.public.tasks.analyze_all_plots',
            'analyze_all_plots_every_3_days',
            Schedule.MINUTES,
            minutes=60 * 24 * 3,
        )
        _ensure_schedule(
            'apps.public.tasks.fetch_weather_all_plots',
            'fetch_plot_weather_daily',
            Schedule.CRON,
            cron='0 18 * * *',
        )
        # Dedicated NDVI/NDMI refresh every 3 days (alongside full analyze pipeline).
        _ensure_schedule(
            'apps.public.tasks.fetch_vegetation_all_plots',
            'fetch_vegetation_all_plots_every_3_days',
            Schedule.MINUTES,
            minutes=60 * 24 * 3,
        )
    except Exception as exc:
        logger.debug('Could not setup periodic tasks: %s', exc)
