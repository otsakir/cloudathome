FROM haproxy:2.8-alpine
RUN mkdir -p /var/lib/haproxy/sockets && chown -R haproxy:haproxy /var/lib/haproxy
USER haproxy