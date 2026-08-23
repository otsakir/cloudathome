from django.db import migrations

from tunnels.ssh.manage_home import tunnel_manager


def provision_homes(apps, schema_editor):
    # Reads the live MAX_HOME_COUNT rather than a frozen literal: on a fresh install
    # this provisions exactly as many Home slots as the deployment is configured for.
    # On an already-migrated database this migration doesn't re-run, so raising
    # MAX_HOME_COUNT later still needs a separate backfill step, not an edit here.
    Home = apps.get_model('homes', 'Home')
    for i in range(tunnel_manager.config.MAX_HOME_COUNT):
        Home.objects.get_or_create(home_index=i)


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0002_remove_proxymapping_slug'),
    ]

    operations = [
        migrations.RunPython(provision_homes, migrations.RunPython.noop),
    ]
