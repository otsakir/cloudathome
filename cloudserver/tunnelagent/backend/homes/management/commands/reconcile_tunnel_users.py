import pwd

from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError

from homes.models import Home
from homes.services import ElevatedOperations


class Command(BaseCommand):
    help = 'Recreates missing system SSH users for all assigned homes'

    def handle(self, *args, **options):
        try:
            homes = list(Home.objects.filter(user__isnull=False).select_related('user'))
        except (OperationalError, ProgrammingError):
            self.stdout.write('Database not ready, skipping reconciliation')
            return

        reconciled = 0
        for home in homes:
            try:
                pwd.getpwnam(home.get_username)
            except KeyError:
                try:
                    ElevatedOperations.add_home_user(home.home_index, home.user.username, home.public_key)
                    reconciled += 1
                except Exception as e:
                    self.stderr.write(f'Failed to recreate user for home {home.home_index}: {e}')

        self.stdout.write(f'Reconciled {reconciled}/{len(homes)} home users')
