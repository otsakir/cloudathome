# Home-configurable features — reference

Most of what's below is home-operator self-service via the API/Home Console — you don't administer it as the cloud operator — but understanding the rules helps when a home operator reports something not working, and the bandwidth/inbound-port mechanisms do run on your server. The last two sections are cloud-operator-only configuration, grouped here because they're extensions of the same port-routing mechanisms.

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

By default, HTTP/HTTPS proxy mappings publish on this instance's standard port (`CAH_HTTP_PORT`/`CAH_HTTPS_PORT`, `.env` — 80/443 out of the box). The cloud server can also advertise a **shared, system-wide alternate port range** — unlike the TCP range, it's not split per home, since HTTP/HTTPS mappings are routed by hostname (which the cloud already guarantees can't collide across homes), not by port alone. A home requests a custom port via `public_port` when creating a mapping (`POST /api/homes/<slug>/proxy-mappings/<scheme>/`), or discovers what's available via `GET /api/config/inbound-ports/<scheme>/`.

The operator configures the range once, in `.env` (see the main [README](../README.md#deploying-the-cloud-server)):

```
HTTP_INBOUND_PORT_RANGE=8080-8180
HTTPS_INBOUND_PORT_RANGE=8443-8543
```

This single value is threaded through `compose.yaml` (published ports on the `haproxy` container) and `docker/haproxy/haproxy.cfg` (the extra `bind` lines, via HAProxy's own environment-variable expansion) — it's only ever edited in one place. **Changing it requires recreating the `haproxy` and `tunnelagent` containers** (`docker compose up -d --build`), not just a config reload — unlike map updates (which the Runtime API applies live), the actual set of listening ports is fixed for the lifetime of the process.

## Running more than one instance on the same host

`CAH_HTTP_PORT`/`CAH_HTTPS_PORT`/`CAH_API_PORT` exist specifically so this repo can be checked out and run more than once on one machine (e.g. staging alongside production, or several community instances). Only one process can ever bind the real `0.0.0.0:80`/`:443` at a time, so every instance past the first needs either its own host IP (then all can keep the 80/443 defaults, bound to different IPs via `compose.yaml`'s port syntax) or its own non-standard port set in `.env`. This only solves *running* multiple instances on one host — it doesn't make several instances share one public IP on the real ports 80/443. That would need something in front of all of them doing its own SNI/Host-based routing to pick which instance's HAProxy handles a given connection — architecturally similar to what HAProxy itself already does one layer down, but not something this repo provides today.

## Routing Django's admin/API through HAProxy

By default, Django (the admin panel, REST API, and web UI/dashboard) is reachable directly on its own published port, `CAH_API_PORT` (`.env`, default 8000) — bypassing HAProxy entirely; see [Architecture](architecture.md) for how the two containers' ports are otherwise independent. Setting `CAH_HOSTNAME` (`.env`, unset by default) instead routes Django through HAProxy's existing Host-based HTTP routing, on a hostname of your choosing (e.g. `cloud.example.com`) — the same `host_http_backends.map` mechanism homes use, just a fixed entry pointing at a fixed backend instead of a per-mapping dynamic one. This is opt-in and additive: it doesn't replace `CAH_API_PORT`, it gives you the option to stop exposing it once `CAH_HOSTNAME` is working, so only `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` need to stay open at the firewall.

Two things worth knowing before turning it on:

- **HTTP only, for now.** Django has no TLS termination of its own (it runs via `manage.py runserver`, a development server), so there's no HTTPS counterpart to this route yet — enabling `CAH_HOSTNAME` only wires up the HTTP path (`http_frontend`/`host_http_backends.map`), matching the same lack of TLS `CAH_API_PORT` already has today. Don't expose admin credentials or API tokens over this route across an untrusted network without your own TLS-terminating layer in front of it.
- **The hostname is reserved automatically.** Once `CAH_HOSTNAME` is set, `BaseDomainService.validate` refuses to let any home register it — or a domain that overlaps it — as a base domain, the same way two homes are prevented from claiming overlapping domains. If you plan to use `CAH_HOSTNAME`, pick something no home would plausibly need (e.g. a subdomain that's clearly the operator's own, not a shared public suffix).

The map entry is seeded once per container start by `manage.py reconcile_admin_route` (run from `docker/django/entrypoint.sh`, alongside `reconcile_tunnel_users`/`reconcile_bandwidth`) — map files start empty on every restart, and nothing else re-registers this one, unlike a home's own mappings.
