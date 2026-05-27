import os

from django.apps import AppConfig
from threading import Thread

# run this inside a thread to make sure everything is in place after it runs
def _sync_mappings():
    from domains.services import SyncService

    if not os.environ.get('RUN_MAIN'):
        ok_count, nok_count = SyncService.sync_all()
        print(f'\n[sync mappings]'
              f'\n succeeded  : {ok_count}'
              f'\n failed     : {nok_count}'
              )

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
            deploy_path = cfg.certbot.deploy_path or '(not set)'
            print(
                f'\n[cloudlink]'
                f'\n  cloud server : {cfg.cloudserver_url}'
                f'\n  home slug    : {cfg.home_slug}'
                f'\n  ssh          : {cfg.ssh.username}@{cfg.ssh.host}:{cfg.ssh.port}'
                f'\n  key          : {cfg.ssh.private_key_path}'
                f'\n  database     : {cfg.database}'
                f'\n  cert deploy  : {deploy_path}\n'
            )
            print(
                f'[features]'
                f'\n  lan forwarding : {cfg.features.lan_forwarding}\n'
            )

        # sync proxy mappings with cloud side
        Thread(target=_sync_mappings, daemon=True).start()
