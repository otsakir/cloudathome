from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError

from homes.models import ProxyMapping
from homes.services import HAProxyService


class Command(BaseCommand):
    help = 'Syncs all proxy mappings from the database to HAProxy'

    def handle(self, *args, **options):
        try:
            mappings = list(ProxyMapping.objects.select_related('home').all())
        except (OperationalError, ProgrammingError):
            self.stdout.write('Database not ready, skipping proxy mapping sync')
            return

        try:
            HAProxyService.sync_mappings(mappings)
        except Exception as e:
            self.stderr.write(f'Failed to sync proxy mappings to HAProxy: {e}')
            return

        self.stdout.write(f'Synced {len(mappings)} proxy mapping(s) to HAProxy')
