from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cloudlink', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(name='CloudConfig'),
    ]
