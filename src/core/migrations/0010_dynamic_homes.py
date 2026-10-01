import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_unclaimed_homes(apps, schema_editor):
    # Leftover empty slots from when 0003 pre-provisioned them -- homes are now
    # created on claim, so a Home row always has an owner.
    Home = apps.get_model('homes', 'Home')
    Home.objects.filter(user__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0009_alter_homebasedomain_options'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(delete_unclaimed_homes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='home',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='homes', to=settings.AUTH_USER_MODEL),
        ),
    ]
