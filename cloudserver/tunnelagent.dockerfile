FROM python:3.12-alpine


# install os system packages
RUN apk add --no-cache openssh bash su-exec sudo && \
    mkdir -p /var/run/sshd && \
    ssh-keygen -A

# Create admin ssh user
RUN adduser -D admin && echo "admin:*" | chpasswd -e && cd /home/admin && \
    mkdir .ssh && chmod 700 .ssh && chown admin:admin .ssh

WORKDIR /home/admin/.ssh
COPY ./docker/tunnelagent/admin/authorized_keys .
RUN chmod 600 authorized_keys && chown admin:admin authorized_keys

# set up Django app
WORKDIR /opt/app
COPY tunnelagent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# create django user
RUN addgroup -S django && adduser -S django -G django

RUN mkdir /opt/backend-var
COPY ./tunnelagent/backend-var/db.sqlite3 /opt/backend-var/
RUN chown -R django:django /opt/backend-var

RUN mkdir -p /var/tunnelagent/public_keys
RUN chown -R django:django /var/tunnelagent
RUN chmod -R 700 /var/tunnelagent

# tunnel users management scripts
COPY tunnelagent/backend/external/tunnels/manage_tunnel.py /usr/local/bin/
RUN chmod 700 /usr/local/bin/manage_tunnel.py
COPY ./docker/tunnelagent/sudoers.d/tunneling /etc/sudoers.d/
RUN chmod 440 /etc/sudoers.d/tunneling

#COPY . /opt/app # we map django code with 'volumes' in compose.yaml


WORKDIR /
# Secure SSH
RUN echo "PermitRootLogin no" >> /etc/ssh/sshd_config && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config && \
    echo "AllowUsers admin" > /etc/ssh/sshd_config.d/01-allowed_users.conf

# Expose SSH port
#EXPOSE 22

COPY docker/tunnelagent/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

## Start SSH daemon
#CMD ["/usr/sbin/sshd", "-D"]


ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]