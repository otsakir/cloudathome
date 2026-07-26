FROM haproxytech/haproxy-alpine:3.0
USER root
# Create the maps directory and an empty map file owned by haproxy.
# Docker initializes the named volume (haproxy_maps) from these image contents on
# first run, giving the haproxy process write access and satisfying HAProxy's
# requirement that the map file exists at startup.
RUN mkdir -p /usr/local/etc/haproxy/maps && \
    touch /usr/local/etc/haproxy/maps/sni_backends.map \
          /usr/local/etc/haproxy/maps/host_http_backends.map \
          /usr/local/etc/haproxy/maps/tcp_backends.map && \
    chown -R haproxy:haproxy /usr/local/etc/haproxy/maps
USER haproxy
