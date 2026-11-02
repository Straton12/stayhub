# tours/apps.py
from django.apps import AppConfig


class ToursConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tours'

    def ready(self):
        try:
            from . import signals  # noqa
        except Exception:
            pass