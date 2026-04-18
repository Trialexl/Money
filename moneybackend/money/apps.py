from django.apps import AppConfig


class MoneyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'money'

    def ready(self):
        from .sync import register_sync_signals

        register_sync_signals()
