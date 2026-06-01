#!/bin/sh
set -e

trap 'echo "Stopping..."; kill $(jobs -p); exit 0' SIGTERM

chown -R django:django /opt/backend-var

/usr/sbin/sshd

su-exec django python /opt/app/manage.py migrate --noinput
su-exec django python /opt/app/manage.py reconcile_tunnel_users
su-exec django python /opt/app/manage.py reconcile_bandwidth

# Register the cloud admin domain in HAProxy's SNI map so that
# https://<CLOUD_DOMAIN> is routed to this container by HAProxy.
if [ -n "$CLOUD_DOMAIN" ]; then
    su-exec django python -c "
import os, socket
s = socket.socket()
s.connect(('haproxy', 9999))
s.sendall(f\"add map /usr/local/etc/haproxy/maps/sni_backends.map {os.environ['CLOUD_DOMAIN']} tunnelagent_django\n\".encode())
s.shutdown(socket.SHUT_WR)
s.close()
print(f\"Registered {os.environ['CLOUD_DOMAIN']} in HAProxy SNI map\")
"
fi

su-exec django gunicorn cloudserver.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --certfile /certs/fullchain.pem \
    --keyfile /certs/privkey.pem \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - &

wait
