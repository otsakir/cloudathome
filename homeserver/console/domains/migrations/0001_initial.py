import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Domain',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=253, unique=True)),
                ('cert_status', models.CharField(
                    choices=[('pending', 'Pending'), ('valid', 'Valid'), ('expired', 'Expired')],
                    default='pending',
                    max_length=10,
                )),
                ('cert_expiry', models.DateTimeField(blank=True, null=True)),
                ('cert_path', models.CharField(blank=True, max_length=512)),
            ],
        ),
        migrations.CreateModel(
            name='ProxyEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cloudserver_host', models.CharField(max_length=253, unique=True)),
                ('tunnel_port', models.IntegerField()),
                ('home_port', models.IntegerField()),
                ('scheme', models.CharField(
                    choices=[('http', 'HTTP'), ('https', 'HTTPS')],
                    default='https',
                    max_length=5,
                )),
                ('tunnel_pid', models.IntegerField(blank=True, null=True)),
                ('tunnel_status', models.CharField(
                    choices=[('closed', 'Closed'), ('open', 'Open'), ('error', 'Error')],
                    default='closed',
                    max_length=6,
                )),
                ('domain', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='proxy_entries',
                    to='domains.domain',
                )),
            ],
        ),
    ]
