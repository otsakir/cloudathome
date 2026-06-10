from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0005_alter_proxymapping_scheme'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ProxyMapping',
        ),
    ]
