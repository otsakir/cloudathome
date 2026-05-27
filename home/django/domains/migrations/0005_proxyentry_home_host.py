from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('domains', '0004_alter_domain_deploy_path'),
    ]

    operations = [
        migrations.AddField(
            model_name='proxyentry',
            name='home_host',
            field=models.CharField(default='localhost', max_length=253),
        ),
    ]
