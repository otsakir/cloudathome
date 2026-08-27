# Home-configurable features — reference

These features are entirely home-operator self-service via the API/Home Console — you don't administer them as the cloud operator — but understanding the rules helps when a home operator reports something not working, and the bandwidth/inbound-port mechanisms below do run on your server.

## Base domains

Before creating any HTTP/HTTPS proxy entry, a home must register at least one base domain with the cloud server. A base domain is a domain the operator controls in DNS — the cloud enforces that no two homes can claim the same domain or overlapping domains (e.g. if Home A owns `example.com`, Home B cannot register `sub.example.com`), and validates that it's a proper registrable domain (not a bare TLD like `com` or a public suffix like `co.uk`) using the Public Suffix List. Subdomains do not need to be registered separately — once `example.com` is registered, the home can freely create proxy entries for `blog.example.com`, `api.example.com`, etc.

## Bandwidth throttling

A home operator caps their own egress bandwidth via `PATCH /api/homes/<slug>/` (`bandwidth_limit_kbps`, range 100–10,000,000 kbps, `null` = unlimited) — but the enforcement runs on the cloud server, so it's worth knowing what it does there. When a limit is set, the cloud server runs, for that home's assigned port range:

```
tc qdisc add dev eth0 root handle 1: htb default 999
tc class add dev eth0 parent 1: classid 1:<N> htb rate <X>kbit ceil <X>kbit
tc filter add dev eth0 parent 1: handle <N> fw classid 1:<N>
iptables -t mangle -A OUTPUT -p tcp --sport <port_low>:<port_high> -j MARK --set-mark <N>
```

All egress TCP traffic sourced from the home's tunnel port range is marked, then shaped through the HTB leaf class at the configured rate; unrelated traffic on the server is unaffected. Since `tc`/`iptables` rules don't survive a container restart, the `reconcile_bandwidth` management command re-applies all limits from the database automatically on container start — the operator doesn't need to do this manually.

## Custom HTTP/HTTPS inbound ports

By default, HTTP/HTTPS proxy mappings publish on the standard port (80/443). The cloud server can also advertise a **shared, system-wide alternate port range** — unlike the TCP range, it's not split per home, since HTTP/HTTPS mappings are routed by hostname (which the cloud already guarantees can't collide across homes), not by port alone. A home requests a custom port via `public_port` when creating a mapping (`POST /api/homes/<slug>/proxy-mappings/<scheme>/`), or discovers what's available via `GET /api/config/inbound-ports/<scheme>/`.

The operator configures the range once, in `.env` (see the main [README](../README.md#deploying-the-cloud-server)):

```
HTTP_INBOUND_PORT_RANGE=8080-8180
HTTPS_INBOUND_PORT_RANGE=8443-8543
```

This single value is threaded through `compose.yaml` (published ports on the `haproxy` container) and `docker/haproxy/haproxy.cfg` (the extra `bind` lines, via HAProxy's own environment-variable expansion) — it's only ever edited in one place. **Changing it requires recreating the `haproxy` and `tunnelagent` containers** (`docker compose up -d --build`), not just a config reload — unlike map updates (which the Runtime API applies live), the actual set of listening ports is fixed for the lifetime of the process.
