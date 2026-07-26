from django.apps import AppConfig


class TunnelsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tunnels'
    label = 'homes'  # preserve existing DB table names and migration history
