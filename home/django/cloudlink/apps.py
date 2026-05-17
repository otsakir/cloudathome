import os

from django.apps import AppConfig


class CloudlinkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cloudlink'

    def ready(self):
        from cloudlink.config import get_config
        try:
            cfg = get_config()
        except FileNotFoundError as e:
            raise SystemExit(f'\n[cloudlink] {e}\n')
        except ValueError as e:
            raise SystemExit(f'\n[cloudlink] Invalid configuration: {e}\n')
        if not os.environ.get('RUN_MAIN'):
            print(
                f'\n[cloudlink]'
                f'\n  cloud server : {cfg.cloudserver_url}'
                f'\n  home slug    : {cfg.home_slug}'
                f'\n  ssh          : {cfg.ssh.username}@{cfg.ssh.host}:{cfg.ssh.port}'
                f'\n  key          : {cfg.ssh.private_key_path}\n'
            )
