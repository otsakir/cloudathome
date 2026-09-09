# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CloudAtHome** enables home-hosted application servers to be reachable from the internet via a cloud proxy. This repo is the cloud-side component: it manages SSH reverse tunnels and HAProxy routing rules. The home-side component (the `cah.py` CLI and Home Console Django app that homes run locally to register and establish tunnels) lives in a separate repo: [otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client).

Locally, that repo checks out as a sibling directory, `../cloudathome-client` relative to this one. Work spanning both sides of the system (e.g. a change to the REST API contract, or the `CloudServerClient`/`HAProxyService` URL shapes staying in sync) is typically done from a single Claude Code session rooted here, `cd`-ing into `../cloudathome-client` as needed rather than starting a separate session per repo.

## Running & Building

Docker Compose needs `CAH_HTTP_PORT`/`CAH_HTTPS_PORT`/
`HTTP_INBOUND_PORT_RANGE`/`HTTPS_INBOUND_PORT_RANGE`/
`TCP_PUBLIC_PORT_RANGE`/`CAH_SSH_PORT`/`HAPROXY_API_PORT` set (see `.env.example`)
before it will start at all — `cp .env.example .env` once per checkout. Without
it, `docker compose up`/`config` fails outright (`no port specified: :<empty>`),
since these vars are substituted directly into `ports:` and into `haproxy.cfg`'s
`bind`/`stats socket` lines. `CAH_HOSTNAME` must also be set to a real hostname
— it's the only way to reach Django, and `manage.py reconcile_admin_route`
aborts container startup outright if it's unset (see "Key design points"
below) — and a TLS cert/key pair must exist at `docker/django/certs/`
(`fullchain.pem`/`privkey.pem`) for gunicorn's HTTPS process to start.

`docker compose up --build` also needs `python3 scripts/generate_fleet_config.py`
to have been run first, once per checkout, after `.env` exists (edit the
`MAX_HOME_COUNT`/`PORTS_PER_HOME`/etc. fleet-size vars in `.env` first if you're
not keeping the defaults — see the comment above them there). That script
validates those vars, writes the tunnel backend stanzas into
`docker/haproxy/haproxy.cfg`, derives `TCP_PUBLIC_PORT_RANGE` back into `.env`,
and writes `docker/django/fleet_config.json`, which `django.dockerfile` `COPY`s
into the image — the build fails outright if that file is missing. It refuses to
run again once `src/var/db.sqlite3` exists, since fleet-size is an install-time-only
decision (see "Key design points" below).

All services run via Docker Compose:

```bash
# Build and start all services
docker compose -f compose.yaml up --build

# Start individual services
docker compose -f compose.yaml up tunnelagent
docker compose -f compose.yaml up haproxy
```

### Django (local development, outside Docker)

```bash
cd src
source .venv/bin/activate

# Run dev server
python manage.py runserver 0.0.0.0:8000

# Run all tests
python manage.py test

# Run a specific test module
python manage.py test tunnels.tests

# Migrations
python manage.py makemigrations
python manage.py migrate
```

Use `DJANGO_SETTINGS_MODULE=config.settings.local_settings` for local dev (SQLite, DEBUG=True). Docker uses `config.settings.docker_settings`.

In local dev `HAPROXY_ENABLED=False` so HAProxy calls are skipped silently.

### Standalone pytest suite for `manage_home.py`

`testsuite/` is a separate pytest project (not Django's test runner) that exercises `TunnelManager`/`BandwidthManager` logic in isolation via `tmp_path` fixtures:

```bash
cd testsuite
pytest
```

`pytest.ini` points `pythonpath` at `../src`, so it imports `tunnels.ssh.manage_home` directly. There's also a Django-integrated test module at `src/tunnels/tests/test_tunnels.py` covering similar ground via `manage.py test`.

### Home management script (requires sudo)

```bash
sudo python src/tunnels/ssh/manage_home.py add <suffix> <home_id> -p <pubkey_file>
sudo python src/tunnels/ssh/manage_home.py remove <suffix> <home_id>
sudo python src/tunnels/ssh/manage_home.py update-key <suffix> <home_id> -p <pubkey_file>
sudo python src/tunnels/ssh/manage_home.py reload

sudo python src/tunnels/ssh/manage_home.py bandwidth set <home_id> --rate <kbps>
sudo python src/tunnels/ssh/manage_home.py bandwidth unset <home_id>
```

`add` and `remove` do not reload sshd automatically; `reload` must be called separately (as `ElevatedOperations` in `tunnels/services.py` does). `remove` also cleans up any bandwidth limit for the home. In the deployed container the script is installed on `PATH` as `manage_home.py`, which is how `ElevatedOperations` invokes it via `sudo`.

## Architecture

### Components

| Component | Port(s) | Role |
|-----------|---------|------|
| **HAProxy** (cloud proxy) | a configurable HTTP/HTTPS standard port pair (`CAH_HTTP_PORT`/`CAH_HTTPS_PORT`, `.env`; default 80/443), a configurable shared HTTP/HTTPS inbound range (`HTTP_INBOUND_PORT_RANGE`/`HTTPS_INBOUND_PORT_RANGE`, `.env`), a configurable raw TCP forward range (`TCP_PUBLIC_PORT_RANGE`, `.env`; default 10000–10099), a configurable Runtime API port (`HAPROXY_API_PORT`, `.env`; default 9999) | SNI-based HTTPS ingress, Host-based HTTP ingress, and raw TCP passthrough; routes traffic to per-home SSH tunnel ports via map files |
| **Django** (`tunnelagent`: Django + sshd, gunicorn) | no published port of its own — reachable only through HAProxy at `CAH_HOSTNAME` (`.env`, required), over both HTTP and HTTPS at `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` — plus a configurable SSH port (`CAH_SSH_PORT`, `.env`; default 8022) | REST API + web UI for managing homes/proxy mappings; SSH server that accepts reverse tunnels from home networks |

### Request & tunnel flow

1. A home network registers by `POST /api/homes/` (via `cloudathome-client`'s `cah.py register`) with its SSH public key.
2. Django calls `ElevatedOperations.add_home_user()` (in `tunnels/services.py`), which sudo-executes `manage_home.py`.
3. `manage_home.py` creates a system user (`home<ID>_<username>`), installs the SSH key, and configures per-user `sshd` restrictions (TCP-forward only, no TTY/shell, allowed port range scoped to that home's block).
4. The home network's gateway opens an SSH reverse tunnel on a port from its assigned range.
5. The home registers one or more **base domains** (`POST /api/homes/<slug>/base-domains/`), then calls `POST /api/homes/<slug>/proxy-mappings/<scheme>/` (scheme = `http`/`https`, hostname must be under a registered base domain; optional `public_port` — defaults to 80/443, or a port from the shared range advertised by `GET /api/config/inbound-ports/<scheme>/`) or `POST /api/homes/<slug>/proxy-mappings/tcp/` (raw TCP, using a public port from the home's dedicated TCP port range). The cloud allocates a free tunnel port from the home's range, updates the HAProxy map via the Runtime API, and returns the allocated port. No mapping state is persisted in the cloud database — HAProxy's live maps are the source of truth.
6. HAProxy routes incoming HTTPS traffic by SNI hostname + public port, HTTP traffic by Host header + public port, and TCP traffic by public port alone, to the matching tunnel backend.
7. Optionally, a home can set a per-home egress **bandwidth limit** (`PATCH /api/homes/<slug>/` with `bandwidth_limit_kbps`), enforced via `tc` HTB classes + `iptables` fwmark rules on the tunnel's outbound interface.

### Key design points

- **Privilege separation**: Django runs as the unprivileged `django` user. Tunnel management requires root; it is invoked via a tightly scoped sudoers rule (`docker/django/sudoers.d/tunneling`) that permits only the `manage_home.py` script.
- **Port allocation**: Each home slot gets a block of 10 SSH tunnel ports starting at `2000 + (home_index * 100)` (stride of 100 leaves headroom per home), plus a block of 10 dedicated public TCP ports starting at `10000 + (home_index * 10)` for raw TCP forwards.
- **Max homes**: 10 (indices 0–9), enforced in the `Home` model and in `manage_home.py`'s `Config`.
- **Username format**: `home<XX>_<django_username>` (e.g. `home00_alice`). The Django username is the SSH suffix.
- **Public keys** are staged to `/var/tunnelagent/public_keys/` before being passed to `manage_home.py`.
- **HAProxy routing**: tunnel backends are pre-created in `haproxy.cfg` for the full SSH port range and the TCP public port range. Three runtime map files drive routing: `sni_backends.map` (HTTPS SNI → backend), `host_http_backends.map` (HTTP Host → backend), `tcp_backends.map` (public TCP port → backend). All are updated at runtime via the HAProxy Runtime API on port 9999 and start empty on each container start; homes are responsible for re-registering their mappings after a restart.
- **Standard HTTP/HTTPS ports are configurable, not hardcoded** (`CAH_HTTP_PORT`/`CAH_HTTPS_PORT`, `.env`; default 80/443), specifically so more than one CloudAtHome instance can run on the same host — each needs its own host IP, or its own non-standard ports, since only one process can ever bind real `0.0.0.0:80`/`:443` at a time. They're threaded into `haproxy.cfg`'s `https_frontend`/`http_frontend` `bind "*:$VAR"` lines the same way as the alternate range below, and are also read by Django (`settings.CAH_HTTP_PORT`/`CAH_HTTPS_PORT`) as the ports `CAH_HOSTNAME` itself is reached on — so they must always match what `haproxy.cfg` actually binds for this instance. **Deliberately independent of `HTTP_INBOUND_DEFAULT_PORT`/`HTTPS_INBOUND_DEFAULT_PORT`** (`.env`; default 80/443 too) — Django's own settings attribute (`tunnels.services.DEFAULT_SCHEME_PORTS`) is the default `public_port` a mapping gets when a home omits it, a separate concern from "this instance's own standard port" that shouldn't move just because an operator retargets `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` for multi-instance-on-one-host reasons. Both get their own `bind "*:$VAR"` line in `haproxy.cfg`, alongside the shared range below — HAProxy enables `SO_REUSEPORT` on its listeners by default, so any of these three bind lines are free to coincide in value without conflict (verified directly against `haproxytech/haproxy-alpine:3.0`: overlapping/duplicate `bind` lines on the same port start and serve traffic fine; same for duplicate `compose.yaml` `ports:` entries, which Compose silently dedupes). `HTTP_INBOUND_DEFAULT_PORT`'s unset default tracks `CAH_HTTP_PORT` (`local_settings.py`), so a fresh `.env` behaves exactly as if this setting didn't exist.
- **Routing Django through HAProxy**: `CAH_HOSTNAME` (`.env`, required) is the only way to reach Django (admin/API/web UI) — there's no separate published port. `CAH_HOSTNAME` must also be added to `ALLOWED_HOSTS` (`local_settings.py`) — Django 400s with `DisallowedHost` on every request otherwise, regardless of `DEBUG`. `manage.py reconcile_admin_route` (run from `docker/django/entrypoint.sh` on every container start, since map files start empty on restart, same as home mappings) seeds map entries via `HAProxyService.ensure_admin_route`, which always `del map`s a key before `add map`-ing it — a bare `add map` would leave a stale duplicate (and, since a map's first match wins, the *stale* value) behind if this ever re-runs against an already-populated map, e.g. restarting only `tunnelagent` (not `haproxy`) after a cert appears/disappears. Django runs under **gunicorn**, not `manage.py runserver`, as two processes: plain HTTP always, on 8000; HTTPS on 8001, **only if** `docker/django/certs/{fullchain,privkey}.pem` are both present (checked independently, same fixed paths, by `entrypoint.sh` and `HAProxyService.https_available` — no ACME automation, no separate on/off setting, cert presence alone is the toggle. `privkey.pem`'s host-side permissions carry through the bind mount — `certbot`/`openssl`'s usual `0600` isn't readable by the container's `django` user; needs `chmod 644`, see `docker/django/certs/README.md`). Whichever entrypoints ended up enabled are reported to `docker logs tunnelagent` by both `entrypoint.sh` and `reconcile_admin_route`. Without a cert, `host_http_backends.map`'s entry is `<CAH_HOSTNAME>:<CAH_HTTP_PORT> → cah_django_http_backend` (proxies straight through); with one, it's `→ cah_django_http_redirect_backend` instead (a 301 to HTTPS, `http-request redirect scheme https`, never reaching Django) and `sni_backends.map` gets `<CAH_HOSTNAME>:<CAH_HTTPS_PORT> → cah_django_https_backend` — all three are fixed (not per-home-generated) backends declared directly in `haproxy.cfg`, the first and third pointing at `tunnelagent:8000`/`tunnelagent:8001` respectively; `cah_django_https_backend` is plain TCP passthrough, exactly like a home's own HTTPS backend, since HAProxy never decrypts it. `reconcile_admin_route` aborts container startup (`CommandError`) if `CAH_HOSTNAME` is unset. `BaseDomainService.validate` refuses to let any home register `CAH_HOSTNAME`, or a domain overlapping it, as a base domain — same overlap check already used between homes' own domains, just against this one reserved value. `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` may safely overlap `HTTP_INBOUND_PORT_RANGE`/`HTTPS_INBOUND_PORT_RANGE` below — HAProxy enables `SO_REUSEPORT` on its listeners by default, so two `bind` lines claiming the same physical port coexist fine (verified: both stay up, both get traffic), and routing itself is decided purely by hostname/SNI, never by which bind line accepted the connection.
- **HTTP/HTTPS inbound port range**: in addition to the standard port pair above, `https_frontend`/`http_frontend` also bind a configurable shared range (`HTTP_INBOUND_PORT_RANGE`/`HTTPS_INBOUND_PORT_RANGE`, threaded from the root `.env` through `compose.yaml` and into `haproxy.cfg`'s `bind "*:$VAR"` lines via HAProxy's own env-var expansion — see `docker/haproxy/haproxy.cfg`). Unlike the TCP range, this range is **not split per home** — any home may use any port in it, because HTTP/HTTPS mappings are routed by hostname, and `BaseDomainService` already guarantees hostnames can't collide across homes. To make that safe, `sni_backends.map`/`host_http_backends.map` keys are composite `hostname:port` (built via `tcp-request content set-var(txn.dstport) dst_port` / `http-request set-var(txn.dstport) dst_port` + `concat(:,txn.dstport,)` in the `use_backend` line), so a mapping only matches the specific port it was registered on. The HTTP side's key needs `req.hdr(host),lower,field(1,':'),concat(...)` — `field(1,':')` strips a port the client may already have included in `Host` (mandatory there on any non-default port, per RFC 7230; browsers/curl only omit it on 80) before `concat` appends the real one, or a request on a non-standard port double-includes it (`host:81:81` vs. the seeded `host:81`) and 503s via `http_default_backend`/`NOSRV`. SNI (`req_ssl_sni`, the HTTPS side) never carries a port at the protocol level, so it doesn't need the same treatment. `HAProxyService.add_mapping`/`dump_mappings`/`mapping_exists` (`tunnels/services.py`) build and parse these composite keys — which is also why the same hostname may hold independent mappings at more than one port simultaneously: `SchemeProxyMappingCreateView`/`SchemeProxyMappingDestroyAPIView` key create/delete on the full `(scheme, host, port)` triple via `mapping_exists`, not on host alone. A home requests a custom port via `public_port` on `POST .../proxy-mappings/<scheme>/`, validated against `settings.HTTP_INBOUND_PORT_RANGE`/`HTTPS_INBOUND_PORT_RANGE`. Changing the range in `.env` requires recreating the `haproxy`/`tunnelagent` containers (env vars are read at container start, not by the seamless `SIGUSR2` config reload) — see `GET /api/config/inbound-ports/<scheme>/` for how a home discovers the current range. `TCP_PUBLIC_PORT_RANGE`, `CAH_SSH_PORT`, and `HAPROXY_API_PORT` follow the same env-var-into-`compose.yaml`/`haproxy.cfg` pattern, but purely to eliminate hardcoded-in-multiple-places duplication. Unlike the HTTP/HTTPS range, `TCP_PUBLIC_PORT_RANGE` is not hand-set: `scripts/generate_fleet_config.py` derives it from `TCP_PUBLIC_PORTS_BASE`/`MAX_HOME_COUNT`/`TCP_PUBLIC_PORTS_PER_HOME` (in `manage_home.py`'s `Config`) and overwrites it in `.env` at install time (see "Running & Building" above), so the two can no longer drift out of sync by hand.
- **Base domains**: a home must register a base domain (`HomeBaseDomain`) before it can create HTTP/HTTPS mappings for hostnames under it. `BaseDomainService` prevents one home from registering a domain that overlaps (as parent or subdomain) with another home's registered domain, and blocks domain removal while live HAProxy mappings still exist under it. By default a domain must also be real and registrable (Public Suffix List, via `tldextract`) — `BASE_DOMAIN_ALLOW_NON_REGISTRABLE` (`.env`, dev/testing only) relaxes just that one check (e.g. `localhost`, `myapp.local` become valid), never the `CAH_HOSTNAME`-reservation or cross-home overlap checks.
- **Bandwidth limiting**: `BandwidthManager` (in `manage_home.py`) creates an HTB class per home on the tunnel-facing interface and an `iptables` mangle rule that marks packets sourced from that home's SSH tunnel port range, so the limit applies regardless of which mapping/service is using the tunnel.
- **Home ownership**: `Home.user` is a FK to Django's `User` with `PROTECT` — a user cannot be deleted while they have assigned homes. A user may hold at most one home slot.
- **Reconciliation**: two idempotent management commands re-derive system state from the DB on startup — `reconcile_tunnel_users` (recreates missing Linux users/SSH config) and `reconcile_bandwidth` (re-applies `tc`/`iptables` bandwidth limits). There's also an admin-only `POST /api/admin/homes/sync` endpoint that does the same user-reconciliation on demand.
- **API tokens**: each home-owning user gets a DRF auth token (`HomeConfigService`), used by the home-side agent to call the cloud API. The web UI lets the user rotate this token, which invalidates the old one immediately.

### Source layout

```
.env.example                              # Template for port-range/port env vars; cp to .env
compose.yaml                              # Orchestrates haproxy + tunnelagent (django)
haproxy.dockerfile
django.dockerfile
docker/
├── haproxy/
│   └── haproxy.cfg                       # HAProxy config (SNI/Host/TCP map routing, pre-created tunnel backends)
└── django/
    ├── entrypoint.sh                     # Starts sshd + Django (gunicorn, HTTP + HTTPS)
    ├── certs/                            # Gitignored; operator-supplied cert/key for CAH_HOSTNAME's HTTPS (fullchain.pem/privkey.pem)
    └── sudoers.d/tunneling               # Sudo grant for manage_home.py
testsuite/                                 # Standalone pytest suite (imports src via pythonpath)
├── tests/test_manage_home.py
src/
    ├── requirements.txt
    ├── manage.py
    ├── config/                            # Django project package (settings, urls, wsgi)
    │   ├── urls.py
    │   ├── debug_urls.py                  # drf-spectacular schema/swagger/redoc (DEBUG only)
    │   └── settings/
    │       ├── local_settings.py
    │       └── docker_settings.py
    ├── tunnels/                            # Domain layer: Home model and tunnel/proxy services (app label: 'homes', for DB/migration compat)
    │   ├── models.py                      # Home, HomeBaseDomain
    │   ├── services.py                    # HAProxyService, BaseDomainService, ElevatedOperations (sudo wrapper)
    │   ├── management/commands/
    │   │   ├── reconcile_tunnel_users.py  # Recreates missing system users on startup
    │   │   ├── reconcile_bandwidth.py     # Re-applies tc/iptables bandwidth limits on startup
    │   │   └── reconcile_admin_route.py   # Seeds the CAH_HOSTNAME HTTP+HTTPS map entries; aborts startup if unset
    │   ├── tests/                         # Django-integrated tests for tunnel management
    │   └── ssh/
    │       └── manage_home.py             # Core tunnel user + bandwidth management script (TunnelManager, BandwidthManager)
    ├── api/                                # DRF REST API (thin layer over tunnels/)
    │   ├── views.py
    │   ├── serializers.py
    │   ├── urls.py
    │   └── tests.py
    └── web/                                # MVC web UI
        ├── views.py
        ├── forms.py
        ├── services.py                    # HomeConfigService: builds home config.yaml, manages/rotates API tokens
        └── templates/web/
```

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/homes/` | List caller's assigned homes (auth required) |
| POST | `/api/homes/` | Claim a home slot and install SSH key |
| PATCH | `/api/homes/<slug>/` | Rotate SSH public key and/or set/clear bandwidth limit |
| DELETE | `/api/homes/<slug>/` | Release a home slot (also cascades: removes this home's live HAProxy mappings and registered base domains, and clears its bandwidth limit, so none of it carries over to whoever claims the slot next) |
| GET | `/api/homes/<slug>/base-domains/` | List base domains registered for this home |
| POST | `/api/homes/<slug>/base-domains/` | Register a base domain |
| DELETE | `/api/homes/<slug>/base-domains/<domain>/` | Remove a base domain (must have no active mappings under it) |
| GET | `/api/homes/<slug>/proxy-mappings/` | List caller's active HAProxy mappings (HTTP/HTTPS + TCP) |
| POST | `/api/homes/<slug>/proxy-mappings/<scheme>/` | Allocate a tunnel port and register an HTTP/HTTPS mapping (`scheme` = `http`/`https`, hostname must be under a registered base domain; optional `public_port`, defaults to 80/443 — a hostname may have independent mappings at more than one port) |
| DELETE | `/api/homes/<slug>/proxy-mappings/<scheme>/<host>/<port>/` | Remove an HTTP/HTTPS forwarding rule from HAProxy for that exact `(scheme, host, port)`; each such triple has at most one active mapping, but a host may have several at different ports |
| POST | `/api/homes/<slug>/proxy-mappings/tcp/` | Allocate a tunnel port and register a raw TCP mapping (public port must be in this home's TCP port range) |
| DELETE | `/api/homes/<slug>/proxy-mappings/tcp/<port>/` | Remove a TCP forwarding rule from HAProxy |
| GET | `/api/config/inbound-ports/<scheme>/` | Get the shared, system-wide inbound port range available for HTTP/HTTPS mappings (`scheme` = `http`/`https`) |
| POST | `/api/auth/authtoken/` | Obtain a token (username/password) |
| DELETE | `/api/auth/token/` | Revoke the caller's own token |
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current live HAProxy map entries (admin only) |
| POST | `/api/admin/homes/sync` | Reconcile DB homes with system users (admin only) |

Authentication is session-based (web UI) or token-based (`TokenAuthentication`, for the home-side `cah.py` CLI). All endpoints require a logged-in user. Proxy mappings and base domains are scoped to the caller's own home slot.

### Web UI

Session-authenticated MVC views in `web/` (`web/views.py`, `web/forms.py`, `web/urls.py`) let a signed-up user view their dashboard (a read-only view of live proxy mappings — creating/removing them is done from the home side, not here), generate/rotate their API token (`RotateTokenView` — this is also how a user gets their first token; there's no separate web-form "register a home" flow, that goes through `POST /api/homes/` via the home-side `cah.py register`), edit their SSH key, download a config-template for the home-side client (`ClientConfigView`, secrets left blank), and release their home slot. `web/services.py`'s `HomeConfigService` renders that template and manages the user's DRF token lifecycle.
