#!/bin/sh
set -e

# trap sigterm and stop sshd and django properly
trap 'echo "Stopping Django and sshd..."; kill $(jobs -p); exit 0' SIGTERM

# run sshd and detach
/usr/sbin/sshd

# run django
su-exec django /opt/app/manage.py runserver 0.0.0.0:8000 &

wait


