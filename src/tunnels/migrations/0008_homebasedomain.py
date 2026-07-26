from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('homes', '0007_home_bandwidth_limit_kbps'),
    ]

    operations = [
        migrations.CreateModel(
            name='HomeBaseDomain',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(max_length=253, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('home', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='base_domains', to='homes.home')),
            ],
        ),
    ]
