FROM haproxytech/haproxy-alpine:3.0
#COPY ./docker/haproxy/haproxy.cfg /usr/local/etc/haproxy/haproxy.cfg

#RUN mkdir -p /var/lib/haproxy/sockets && chown -R haproxy:haproxy /var/lib/haproxy
#USER haproxy
#
#EXPOSE 443 5555