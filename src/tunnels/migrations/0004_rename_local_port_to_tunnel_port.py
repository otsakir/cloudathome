from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0003_provision_homes'),
    ]

    operations = [
        migrations.RenameField(
            model_name='proxymapping',
            old_name='local_port',
            new_name='tunnel_port',
        ),
    ]
