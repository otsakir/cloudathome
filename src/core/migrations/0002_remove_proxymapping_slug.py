from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='proxymapping',
            name='slug',
        ),
    ]
