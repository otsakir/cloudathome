FROM nginx:alpine

RUN apk add --no-cache certbot && \
    mkdir -p /var/www/certbot

COPY docker/nginx-acme.conf /etc/nginx/conf.d/default.conf
