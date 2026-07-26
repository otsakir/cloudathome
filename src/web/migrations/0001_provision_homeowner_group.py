from django.db import migrations


def provision_homeowner_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name='homeowner')


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '__latest__'),
    ]

    operations = [
        migrations.RunPython(provision_homeowner_group, migrations.RunPython.noop),
    ]
