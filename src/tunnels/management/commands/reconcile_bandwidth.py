from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError

from tunnels.models import Home
from tunnels.services import ElevatedOperations


class Command(BaseCommand):
    help = 'Re-applies per-home bandwidth limits from the database to tc/iptables'

    def handle(self, *args, **options):
        try:
            homes = list(Home.objects.filter(user__isnull=False))
        except (OperationalError, ProgrammingError):
            self.stdout.write('Database not ready, skipping bandwidth reconciliation')
            return

        for home in homes:
            if not home.bandwidth_limit_kbps:
                continue
            try:
                ElevatedOperations.set_home_bandwidth(home.home_index, home.bandwidth_limit_kbps)
            except Exception as e:
                self.stderr.write(f'Failed to reconcile bandwidth for home {home.home_index}: {e}')

        self.stdout.write(f'Bandwidth reconciliation complete for {len(homes)} home(s)')
