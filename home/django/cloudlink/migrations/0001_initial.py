from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='CloudConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cloudserver_url', models.URLField()),
                ('auth_token', models.CharField(blank=True, max_length=64)),
                ('home_slug', models.SlugField(blank=True)),
                ('ssh_host', models.CharField(blank=True, max_length=253)),
                ('ssh_port', models.IntegerField(default=22)),
                ('ssh_username', models.CharField(blank=True, max_length=64)),
                ('private_key_path', models.CharField(blank=True, max_length=512)),
                ('port_base', models.IntegerField(default=2000)),
                ('port_count', models.IntegerField(default=10)),
            ],
        ),
    ]
