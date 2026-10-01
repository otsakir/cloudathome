from django.db import migrations


# Used to pre-create MAX_HOME_COUNT empty Home rows here. Homes are now created
# on claim and deleted on release (core.services.claim_home/release_home), so
# this is a no-op; 0010_dynamic_homes removes the empty rows older installs
# still have. Kept because it's part of the migration graph.


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0002_remove_proxymapping_slug'),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
