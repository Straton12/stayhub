# laundry/apps.py
from django.apps import AppConfig


class LaundryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'laundry'

    def ready(self):
        try:
            from . import signals  # noqa
        except Exception:
            pass