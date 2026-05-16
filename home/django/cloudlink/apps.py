from django.apps import AppConfig


class CloudlinkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cloudlink'

    def ready(self):
        from cloudlink.config import get_config
        try:
            get_config()
        except FileNotFoundError as e:
            raise SystemExit(f'\n[cloudlink] {e}\n')
        except ValueError as e:
            raise SystemExit(f'\n[cloudlink] Invalid configuration: {e}\n')
