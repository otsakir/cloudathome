from django.db import migrations


def provision_homes(apps, schema_editor):
    Home = apps.get_model('homes', 'Home')
    for i in range(10):
        Home.objects.get_or_create(home_index=i)


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0002_remove_proxymapping_slug'),
    ]

    operations = [
        migrations.RunPython(provision_homes, migrations.RunPython.noop),
    ]
