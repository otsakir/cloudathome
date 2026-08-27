from django.core.management.base import BaseCommand

from tunnels.services import HAProxyService


class Command(BaseCommand):
    help = (
        "Seeds the static HAProxy map entry that routes settings.CAH_HOSTNAME to "
        "this instance's own Django backend. No-op if CAH_HOSTNAME is unset. "
        "HAProxy's map files start empty on every container restart, so this "
        "needs to run on every startup, not just once -- unlike home mappings, "
        "nothing re-registers this one on the home's behalf."
    )

    def handle(self, *args, **options):
        HAProxyService.ensure_admin_route()
        self.stdout.write('Admin route reconciled')
