import autoslug.fields
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Home',
            fields=[
                ('home_index', models.IntegerField(primary_key=True, serialize=False, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(9)])),
                ('public_key', models.TextField(blank=True, max_length=800, null=True)),
                ('slug', models.CharField(blank=True, max_length=32, null=True, unique=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='homes', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ProxyMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('host', models.CharField(max_length=253, unique=True)),
                ('local_port', models.IntegerField()),
                ('scheme', models.CharField(choices=[('https', 'HTTPS')], default='https', max_length=5)),
                ('slug', autoslug.fields.AutoSlugField(editable=False, populate_from='host', unique=True)),
                ('home', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='proxy_mappings', to='homes.home')),
            ],
        ),
    ]
