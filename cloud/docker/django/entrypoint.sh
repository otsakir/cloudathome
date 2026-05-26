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

# run django
su-exec django /opt/app/manage.py runserver 0.0.0.0:8000 &

wait
