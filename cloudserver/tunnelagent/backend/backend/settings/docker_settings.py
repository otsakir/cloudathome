from backend.settings.local_settings import *


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / '../backend-var/db.sqlite3',
    }
}

HAPROXY_ENABLED = True
HAPROXY_API_HOST = 'haproxy'
HAPROXY_API_PORT = 9999

