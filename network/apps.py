# network/apps.py
from django.apps import AppConfig


class NetworkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'network'

    def ready(self):
        try:
            from . import signals  # noqa
        except Exception:
            pass