#!/bin/sh

# start sshd
/usr/sbin/sshd -D &

# start django
python manage.py runserver 0.0.0.0:8000
