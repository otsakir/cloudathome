FROM nginx:alpine

RUN apk add --no-cache openssl && \
    mkdir -p /etc/nginx/ssl && \
    openssl req -x509 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/key.pem \
        -out /etc/nginx/ssl/cert.pem \
        -days 3650 -nodes \
        -subj '/CN=cloudathome-home/O=CloudAtHome'

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/html /usr/share/nginx/html
