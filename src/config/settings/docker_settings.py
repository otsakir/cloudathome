from config.settings.local_settings import *


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / '../backend-var/db.sqlite3',
    }
}

MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware',)
STATIC_URL = '/static/'
# Deliberately NOT under BASE_DIR (/opt/app) -- that's the ./src bind mount
# (see compose.yaml), owned by the host user, not the container's django
# user. collectstatic (run every container start, entrypoint.sh) would fail
# with PermissionError trying to create directories there. /opt/static is a
# container-native path instead, created and chowned to django:django at
# build time (django.dockerfile) -- same pattern as /etc/cloudathome/certs
# and /var/tunnelagent/public_keys.
STATIC_ROOT = '/opt/static'

HAPROXY_ENABLED = True
HAPROXY_API_HOST = 'haproxy'
# HAPROXY_API_PORT is inherited from local_settings (env-var driven, same value).

