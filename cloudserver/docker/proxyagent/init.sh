#!/bin/sh
# Exit immediately if a command exits with a non-zero status. It's an 'all or nothing' logic, good for docker containers.
set -e

# trap SIGTERM and stop sshd and django processes properly
trap 'echo "Stopping Django and sshd..."; kill $(jobs -p); exit 0' SIGTERM

# start sshd
/usr/sbin/sshd -D &

# start django
python manage.py runserver 0.0.0.0:8000 &

wait
