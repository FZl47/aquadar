from django.apps import AppConfig


class PublicConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.public'

    def ready(self):
        from . import signals  # noqa: F401
