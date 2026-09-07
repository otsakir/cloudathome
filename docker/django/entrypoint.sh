#!/bin/sh
set -e

# trap sigterm and stop sshd and django properly
trap 'echo "Stopping Django and sshd..."; kill $(jobs -p); exit 0' SIGTERM

# ensure the django user owns the var directory (bind mount arrives owned by the host user)
chown -R django:django /opt/backend-var

# sshd must start first — reconcile_tunnel_users sends SIGHUP to reload its config
/usr/sbin/sshd

# recreate any system SSH users that are in the database but missing from the container
su-exec django python /opt/app/manage.py reconcile_tunnel_users

# re-apply bandwidth limits from the database (tc rules are lost on container restart)
su-exec django python /opt/app/manage.py reconcile_bandwidth

# re-seed the static admin-route map entry (aborts startup, via `set -e`
# above, if CAH_HOSTNAME is unset -- it's the only way to reach Django now;
# HAProxy's map files are wiped on every restart, same as home mappings)
su-exec django python /opt/app/manage.py reconcile_admin_route

# --noinput: collectstatic otherwise prompts for confirmation whenever the
# destination (settings.STATIC_ROOT, /opt/static -- see django.dockerfile)
# already has files, which it will on every restart of an existing (not
# recreated) container -- would hang here forever waiting on stdin.
su-exec django python /opt/app/manage.py collectstatic --noinput

# run django under gunicorn -- one plain-HTTP process always, one HTTPS
# process only if a cert/key has been supplied (see compose.yaml's certs bind
# mount) -- their mere presence is the toggle, no separate setting. Same fixed
# paths HAProxyService.https_available checks in Python, so the map entries
# reconcile_admin_route just seeded and what actually starts here can never
# disagree. Both are only reachable via HAProxy's cah_django_http_backend/
# cah_django_https_backend (see docker/haproxy/haproxy.cfg) -- there's no
# published port straight to this container anymore.
CERT_FILE=/etc/cloudathome/certs/fullchain.pem
KEY_FILE=/etc/cloudathome/certs/privkey.pem

su-exec django gunicorn config.wsgi:application --chdir /opt/app --bind 0.0.0.0:8000 &

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
  echo "Starting Django HTTPS gunicorn on :8001 (cert: $CERT_FILE)"
  su-exec django gunicorn config.wsgi:application --chdir /opt/app --bind 0.0.0.0:8001 \
      --certfile "$CERT_FILE" \
      --keyfile "$KEY_FILE" &
else
  echo "Skipping Django HTTPS gunicorn -- no cert found at $CERT_FILE (see docker/django/certs/README.md)"
fi

wait
