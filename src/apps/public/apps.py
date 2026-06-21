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
        if not Schedule.objects.filter(func='apps.public.tasks.analyze_all_plots').exists():
            q_schedule(
                'apps.public.tasks.analyze_all_plots',
                schedule_type=Schedule.MINUTES,
                minutes=60 * 24 * 3,
                name='analyze_all_plots_every_3_days',
            )
        weather_sched = Schedule.objects.filter(func='apps.public.tasks.fetch_weather_all_plots').first()
        if weather_sched:
            if weather_sched.schedule_type != Schedule.CRON or weather_sched.cron != '0 18 * * *':
                weather_sched.schedule_type = Schedule.CRON
                weather_sched.cron = '0 18 * * *'
                weather_sched.save(update_fields=['schedule_type', 'cron'])
        else:
            q_schedule(
                'apps.public.tasks.fetch_weather_all_plots',
                schedule_type=Schedule.CRON,
                cron='0 18 * * *',
                name='fetch_plot_weather_daily',
            )
    except Exception:
        pass
