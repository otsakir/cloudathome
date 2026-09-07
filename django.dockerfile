FROM python:3.12-alpine


# install os system packages
RUN apk add --no-cache openssh bash su-exec sudo iproute2 iptables && \
    mkdir -p /var/run/sshd && \
    ssh-keygen -A

# Create admin ssh user
RUN adduser -D admin && echo "admin:*" | chpasswd -e && cd /home/admin && \
    mkdir .ssh && chmod 700 .ssh && chown admin:admin .ssh

WORKDIR /home/admin/.ssh
COPY ./docker/django/admin/authorized_keys .
RUN chmod 600 authorized_keys && chown admin:admin authorized_keys

# set up Django app
WORKDIR /opt/app
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# create django user
RUN addgroup -S django && adduser -S django -G django

#RUN mkdir /opt/backend-var
#COPY ./tunnelagent/backend/db.sqlite3 /opt/backend-var/
#RUN chown -R django:django /opt/backend-var

RUN mkdir -p /var/tunnelagent/public_keys
RUN chown -R django:django /var/tunnelagent
RUN chmod -R 700 /var/tunnelagent

# Mount point for the operator-supplied TLS cert/key gunicorn terminates
# CAH_HOSTNAME's HTTPS with (see compose.yaml's certs bind mount and
# docker/django/entrypoint.sh) -- no ACME automation, files are placed here
# manually.
RUN mkdir -p /etc/cloudathome/certs && chown -R django:django /etc/cloudathome/certs

# collectstatic's output (settings.STATIC_ROOT, docker_settings.py), served by
# WhiteNoise. Deliberately outside /opt/app -- that's the ./src bind mount
# (compose.yaml), owned by the host user; collectstatic (run as django, every
# container start via entrypoint.sh) can't create directories there.
RUN mkdir -p /opt/static && chown -R django:django /opt/static

# tunnel users management scripts
COPY src/tunnels/ssh/manage_home.py /usr/local/bin/
RUN chmod 700 /usr/local/bin/manage_home.py
COPY ./docker/django/sudoers.d/tunneling /etc/sudoers.d/
RUN chmod 440 /etc/sudoers.d/tunneling

# Fleet-size config (MAX_HOME_COUNT and friends), locked at install time by
# scripts/generate_fleet_config.py -- must have been run against .env before this
# build (see that script's docstring). Baked into the image, root-owned, so the
# unprivileged django user can't influence what manage_home.py trusts for these
# values at runtime -- see manage_home.py's module docstring.
RUN mkdir -p /etc/cloudathome
COPY docker/django/fleet_config.json /etc/cloudathome/fleet_config.json
RUN chmod 644 /etc/cloudathome/fleet_config.json

#COPY . /opt/app # we map django code with 'volumes' in compose.yaml


WORKDIR /
# Secure SSH
RUN echo "PermitRootLogin no" >> /etc/ssh/sshd_config && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config && \
    echo "GatewayPorts yes" > /etc/ssh/sshd_config.d/00-prologue.conf && \
    echo "AllowTcpForwarding yes" >> /etc/ssh/sshd_config.d/00-prologue.conf && \
    echo "AllowUsers admin" > /etc/ssh/sshd_config.d/01-allowed_users.conf

# Expose SSH port
#EXPOSE 22

COPY docker/django/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

## Start SSH daemon
#CMD ["/usr/sbin/sshd", "-D"]


ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]