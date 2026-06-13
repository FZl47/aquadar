from django.apps import AppConfig
from django.db.models.signals import post_migrate


class PublicConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.public'

    def ready(self):
        from . import signals
        post_migrate.connect(_setup_periodic_tasks, sender=self)


def _setup_periodic_tasks(sender, **kwargs):
    try:
        from django_q.models import Schedule
        from django_q.tasks import schedule as q_schedule
        if not Schedule.objects.filter(func='apps.public.tasks.retry_failed_weather_fetches').exists():
            q_schedule(
                'apps.public.tasks.retry_failed_weather_fetches',
                schedule_type=Schedule.HOURLY,
                name='retry_weather_fetch',
            )
    except Exception:
        pass
