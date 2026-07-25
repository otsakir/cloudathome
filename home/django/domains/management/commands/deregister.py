from django.core.management.base import BaseCommand, CommandError

from cloudlink.services import CloudServerClient, CloudServerError
from domains.services import SyncService


class Command(BaseCommand):
    help = 'Tear down this profile\'s connection to its cloud server: disconnect tunnels, release the home slot, and revoke the API token'

    def handle(self, *args, **options):
        SyncService.disconnect_all()
        self.stdout.write('Disconnected all tunnels')

        client = CloudServerClient()

        try:
            client.delete_home()
        except CloudServerError as e:
            raise CommandError(f'Failed to release home slot: {e}')
        self.stdout.write('Released home slot')

        try:
            client.revoke_token()
        except CloudServerError as e:
            raise CommandError(f'Failed to revoke API token: {e}')
        self.stdout.write(self.style.SUCCESS('Deregistered from cloud server'))
