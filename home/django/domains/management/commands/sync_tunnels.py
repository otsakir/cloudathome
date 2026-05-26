from django.core.management.base import BaseCommand, CommandError

from domains.models import Domain, ProxyEntry
from domains.services import SyncService


class Command(BaseCommand):
    help = 'Sync tunnels and cloud proxy mappings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--domain',
            metavar='NAME',
            help='Sync only the entry for this domain name',
        )
        parser.add_argument(
            '--disconnect',
            action='store_true',
            help='Disconnect instead of sync',
        )

    def handle(self, *args, **options):
        domain_name = options['domain']
        disconnect = options['disconnect']

        if domain_name:
            domain = Domain.objects.filter(name=domain_name).first()
            if not domain:
                raise CommandError(f'Domain not found: {domain_name}')
            try:
                entry = domain.proxy_entry
            except ProxyEntry.DoesNotExist:
                raise CommandError(f'No proxy entry for domain: {domain_name}')

            if disconnect:
                SyncService.disconnect_entry(entry)
                self.stdout.write(self.style.SUCCESS(f'Disconnected {domain_name}'))
            else:
                try:
                    SyncService.sync_entry(entry)
                    self.stdout.write(self.style.SUCCESS(f'Synced {domain_name}'))
                except Exception as e:
                    raise CommandError(f'Sync failed for {domain_name}: {e}')
        else:
            if disconnect:
                SyncService.disconnect_all()
                self.stdout.write(self.style.SUCCESS('Disconnected all entries'))
            else:
                succeeded, failed = SyncService.sync_all()
                msg = f'Sync complete: {succeeded} succeeded, {failed} failed'
                if failed:
                    self.stdout.write(self.style.WARNING(msg))
                else:
                    self.stdout.write(self.style.SUCCESS(msg))
