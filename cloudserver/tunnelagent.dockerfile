FROM python:3.12-alpine


# Install OpenSSH
RUN apk add --no-cache openssh bash && \
    mkdir -p /var/run/sshd && \
    ssh-keygen -A

# Create user
RUN adduser -D admin && echo "admin:*" | chpasswd -e && cd /home/admin && \
    mkdir .ssh && chmod 700 .ssh && chown admin:admin .ssh

WORKDIR /home/admin/.ssh
COPY ./docker/tunnelagent/admin/authorized_keys .
RUN chmod 600 authorized_keys && chown admin:admin authorized_keys

WORKDIR /
# Secure SSH
RUN echo "PermitRootLogin no" >> /etc/ssh/sshd_config && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config && \
    echo "AllowUsers admin" >> /etc/ssh/sshd_config

# Expose SSH port
EXPOSE 22

# Start SSH daemon
CMD ["/usr/sbin/sshd", "-D"]