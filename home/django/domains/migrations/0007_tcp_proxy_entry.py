from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('domains', '0006_unique_home_host_port'),
    ]

    operations = [
        migrations.AlterField(
            model_name='proxyentry',
            name='domain',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='proxy_entry',
                to='domains.domain',
            ),
        ),
        migrations.AlterField(
            model_name='proxyentry',
            name='cloudserver_host',
            field=models.CharField(blank=True, max_length=253, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='proxyentry',
            name='scheme',
            field=models.CharField(
                choices=[('http', 'HTTP'), ('https', 'HTTPS'), ('tcp', 'TCP')],
                default='https',
                max_length=5,
            ),
        ),
        migrations.AddField(
            model_name='proxyentry',
            name='public_port',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
