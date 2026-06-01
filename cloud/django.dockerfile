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
COPY django/requirements-prod.txt django/requirements.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

# create django user
RUN addgroup -S django && adduser -S django -G django

#RUN mkdir /opt/backend-var
#COPY ./tunnelagent/backend/db.sqlite3 /opt/backend-var/
#RUN chown -R django:django /opt/backend-var

RUN mkdir -p /var/tunnelagent/public_keys
RUN chown -R django:django /var/tunnelagent
RUN chmod -R 700 /var/tunnelagent

# tunnel users management scripts
COPY django/homes/tunnels/manage_home.py /usr/local/bin/
RUN chmod 700 /usr/local/bin/manage_home.py
COPY ./docker/django/sudoers.d/tunneling /etc/sudoers.d/
RUN chmod 440 /etc/sudoers.d/tunneling

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

COPY django /opt/app
RUN DJANGO_SETTINGS_MODULE=cloudserver.settings.cloud_settings \
    SECRET_KEY=build-dummy \
    CLOUD_DOMAIN=build-dummy \
    python /opt/app/manage.py collectstatic --noinput

COPY docker/django/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/django/entrypoint.prod.sh /usr/local/bin/entrypoint.prod.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint.prod.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]