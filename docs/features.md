# Home-configurable features — reference

Most of what's below is home-operator self-service via the API/Home Console — you don't administer it as the cloud operator — but understanding the rules helps when a home operator reports something not working, and the bandwidth/inbound-port mechanisms do run on your server. The last two sections are cloud-operator-only configuration, grouped here because they're extensions of the same port-routing mechanisms.

## Base domains

Before creating any HTTP/HTTPS proxy entry, a home must register at least one base domain with the cloud server. A base domain is a domain the operator controls in DNS — the cloud enforces that no two homes can claim the same domain or overlapping domains (e.g. if Home A owns `example.com`, Home B cannot register `sub.example.com`), and validates that it's a proper registrable domain (not a bare TLD like `com` or a public suffix like `co.uk`) using the Public Suffix List. Subdomains do not need to be registered separately — once `example.com` is registered, the home can freely create proxy entries for `blog.example.com`, `api.example.com`, etc.

For local/dev use, `BASE_DOMAIN_ALLOW_NON_REGISTRABLE=true` (`.env`) relaxes just the registrable-domain check, so things like `localhost` or `myapp.local` become valid base domains too — the overlap checks between homes and the `CAH_HOSTNAME` reservation still apply exactly as before. Never enable this on a real deployment.

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

By default, HTTP/HTTPS proxy mappings publish on `HTTP_INBOUND_DEFAULT_PORT`/`HTTPS_INBOUND_DEFAULT_PORT` (`.env` — 80/443 out of the box). This is deliberately its own setting, not tied to `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` (this instance's own standard port, and `CAH_HOSTNAME`'s route) — see [Running more than one instance on the same host](#running-more-than-one-instance-on-the-same-host) for why that separation matters. The cloud server can also advertise a **shared, system-wide alternate port range** — unlike the TCP range, it's not split per home, since HTTP/HTTPS mappings are routed by hostname (which the cloud already guarantees can't collide across homes), not by port alone. A home requests a custom port via `public_port` when creating a mapping (`POST /api/homes/<slug>/proxy-mappings/<scheme>/`), or discovers what's available via `GET /api/config/inbound-ports/<scheme>/`.

The operator configures the range once, in `.env` (see the main [README](../README.md#deploying-the-cloud-server)):

```
HTTP_INBOUND_PORT_RANGE=8080-8090
HTTPS_INBOUND_PORT_RANGE=8443-8452
```

This single value is threaded through `compose.yaml` (published ports on the `haproxy` container) and `docker/haproxy/haproxy.cfg` (the extra `bind` lines, via HAProxy's own environment-variable expansion) — it's only ever edited in one place. **Changing it requires recreating the `haproxy` and `tunnelagent` containers** (`docker compose up -d --build`), not just a config reload — unlike map updates (which the Runtime API applies live), the actual set of listening ports is fixed for the lifetime of the process.

## Running more than one instance on the same host

`CAH_HTTP_PORT`/`CAH_HTTPS_PORT` exist specifically so this repo can be checked out and run more than once on one machine (e.g. staging alongside production, or several community instances). Only one process can ever bind the real `0.0.0.0:80`/`:443` at a time, so every instance past the first needs either its own host IP (then all can keep the 80/443 defaults, bound to different IPs via `compose.yaml`'s port syntax) or its own non-standard port set in `.env`. This only solves *running* multiple instances on one host — it doesn't make several instances share one public IP on the real ports 80/443. That would need something in front of all of them doing its own SNI/Host-based routing to pick which instance's HAProxy handles a given connection — architecturally similar to what HAProxy itself already does one layer down, but not something this repo provides today.

Because `HTTP_INBOUND_DEFAULT_PORT`/`HTTPS_INBOUND_DEFAULT_PORT` are separate settings from `CAH_HTTP_PORT`/`CAH_HTTPS_PORT`, moving the latter for this reason doesn't drag a home's default `public_port` along with it — an instance can run its own admin/API traffic on a non-standard port while homes still default to 80/443, or vice versa. There's no need to keep the two in sync: HAProxy happily binds all of them (`CAH_HTTP_PORT`, `HTTP_INBOUND_DEFAULT_PORT`, and `HTTP_INBOUND_PORT_RANGE` — same for HTTPS) whether or not their values coincide, since it enables `SO_REUSEPORT` on its listeners by default.

## Routing Django's admin/API through HAProxy

Django (the admin panel, REST API, and web UI/dashboard) has no published port of its own — `CAH_HOSTNAME` (`.env`, required) is the only way to reach it, routed through HAProxy on a hostname of your choosing (e.g. `cloud.example.com`), at this instance's standard `CAH_HTTP_PORT`/`CAH_HTTPS_PORT`. Django runs under **gunicorn** (not `manage.py runserver`), which can hold its own TLS cert, so HTTPS to `CAH_HOSTNAME` works exactly like a home's own HTTPS backend — HAProxy passes the still-encrypted bytes straight through to it (see [Architecture](architecture.md)).

**HTTPS is entirely optional, toggled purely by whether a cert is present** — no separate setting:

- **No cert at `docker/django/certs/{fullchain,privkey}.pem`** → Django is HTTP-only. `host_http_backends.map` gets a fixed entry (`cah_django_http_backend`) proxying straight through, the same mechanism homes' own HTTP mappings use, just a fixed entry instead of a per-mapping dynamic one. No HTTPS route exists at all.
- **Cert present** → gunicorn's HTTPS process starts, `sni_backends.map` gets a fixed entry (`cah_django_https_backend`), *and* the HTTP entry switches to a redirect backend that 301s straight to `https://CAH_HOSTNAME/` without ever reaching Django — plain HTTP access stops being possible the moment a cert shows up.

Two things worth knowing:

- **The operator supplies the cert; permissions matter.** Drop `fullchain.pem`/`privkey.pem` into `docker/django/certs/` (bind-mounted into the `tunnelagent` container — see `compose.yaml`); there's no ACME/Certbot automation for this route. Since it's a bind mount, `privkey.pem`'s host-side ownership/permissions carry straight into the container — tools like `openssl`/`certbot` commonly write it `0600`, which the `django` user gunicorn runs as usually can't read; `chmod 644` it (see `docker/django/certs/README.md`). A missing or unreadable cert fails when gunicorn's HTTPS process tries to start, not at container startup — check `docker logs tunnelagent`.
- **The hostname is reserved automatically.** `BaseDomainService.validate` refuses to let any home register `CAH_HOSTNAME` — or a domain that overlaps it — as a base domain, the same way two homes are prevented from claiming overlapping domains. Pick something no home would plausibly need (e.g. a subdomain that's clearly the operator's own, not a shared public suffix).

The map entries are seeded on every container start by `manage.py reconcile_admin_route` (run from `docker/django/entrypoint.sh`, alongside `reconcile_tunnel_users`/`reconcile_bandwidth`), which reports which of Django's HTTP/HTTPS entrypoints ended up enabled — check `docker logs tunnelagent` if you're unsure why one isn't working. Existing entries are always deleted before being re-added, so restarting just `tunnelagent` (e.g. after dropping in a cert) without also restarting `haproxy` still ends up correct rather than leaving a stale duplicate behind. If `CAH_HOSTNAME` is unset, this command aborts container startup outright, since there'd otherwise be no way to reach Django at all.

Django's standard ports may safely overlap `HTTP_INBOUND_PORT_RANGE`/`HTTPS_INBOUND_PORT_RANGE` (below) — HAProxy enables `SO_REUSEPORT` on its listeners by default, so two `bind` lines claiming the same port coexist without conflict, and routing is decided by hostname/SNI, never by which bind line accepted the connection.
