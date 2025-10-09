# Build stage
FROM python:3.12-alpine as builder

WORKDIR /app
COPY proxyagent-app/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.12-alpine

# Install runtime dependencies only
RUN apk add --no-cache \
    openssh \
    sqlite \
    libstdc++

# Copy Python packages from builder stage
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# SSH configuration
RUN ssh-keygen -A && \
    echo "root:password" | chpasswd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/#Port 22/Port 1122/' /etc/ssh/sshd_config


WORKDIR /app
# do not copy for the time being, instead 'backend' is mapped in  compose.yaml/volumes
# COPY ./proxyagent-app/backend ./backend

#EXPOSE 8000

COPY ./docker/proxyagent/init.sh .
RUN chmod +x ./init.sh

CMD ["./init.sh"]
