# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CloudAtHome** enables home-hosted application servers to be reachable from the internet via a cloud proxy. The cloud server component manages SSH reverse tunnels and HAProxy routing rules. The home server component (in `home/`) connects to the cloud server to register and establish tunnels.

## Running & Building

All services run via Docker Compose from the `cloud/` directory:

```bash
# Build and start all services
docker compose -f cloud/compose.yaml up --build

# Start individual services
docker compose -f cloud/compose.yaml up tunnelagent
docker compose -f cloud/compose.yaml up haproxy
```

### Django (local development, outside Docker)

```bash
cd cloud/src
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

`cloud/testsuite/` is a separate pytest project (not Django's test runner) that exercises `TunnelManager`/`BandwidthManager` logic in isolation via `tmp_path` fixtures:

```bash
cd cloud/testsuite
pytest
```

`pytest.ini` points `pythonpath` at `../src`, so it imports `tunnels.ssh.manage_home` directly. There's also a Django-integrated test module at `cloud/src/tunnels/tests/test_tunnels.py` covering similar ground via `manage.py test`.

### Home management script (requires sudo)

```bash
sudo python cloud/src/tunnels/ssh/manage_home.py add <suffix> <home_id> -p <pubkey_file>
sudo python cloud/src/tunnels/ssh/manage_home.py remove <suffix> <home_id>
sudo python cloud/src/tunnels/ssh/manage_home.py update-key <suffix> <home_id> -p <pubkey_file>
sudo python cloud/src/tunnels/ssh/manage_home.py reload

sudo python cloud/src/tunnels/ssh/manage_home.py bandwidth set <home_id> --rate <kbps>
sudo python cloud/src/tunnels/ssh/manage_home.py bandwidth unset <home_id>
```

`add` and `remove` do not reload sshd automatically; `reload` must be called separately (as `ElevatedOperations` in `tunnels/services.py` does). `remove` also cleans up any bandwidth limit for the home. In the deployed container the script is installed on `PATH` as `manage_home.py`, which is how `ElevatedOperations` invokes it via `sudo`.

## Architecture

### Components

| Component | Port(s) | Role |
|-----------|---------|------|
| **HAProxy** (cloud proxy) | 80/443 (HTTP/HTTPS), 10000–10099 (raw TCP forwards), 9999 (Runtime API) | SNI-based HTTPS ingress, Host-based HTTP ingress, and raw TCP passthrough; routes traffic to per-home SSH tunnel ports via map files |
| **Django** (`tunnelagent`: Django + sshd) | 8000 (API), 8022 (SSH) | REST API + web UI for managing homes/proxy mappings; SSH server that accepts reverse tunnels from home networks |

### Request & tunnel flow

1. A home network registers by `POST /api/homes/` (or via the web UI's "register home" flow) with its SSH public key.
2. Django calls `ElevatedOperations.add_home_user()` (in `tunnels/services.py`), which sudo-executes `manage_home.py`.
3. `manage_home.py` creates a system user (`home<ID>_<username>`), installs the SSH key, and configures per-user `sshd` restrictions (TCP-forward only, no TTY/shell, allowed port range scoped to that home's block).
4. The home network's gateway opens an SSH reverse tunnel on a port from its assigned range.
5. The home registers one or more **base domains** (`POST /api/homes/<slug>/base-domains/`), then calls `POST /api/homes/<slug>/proxy-mappings/<scheme>/` (scheme = `http`/`https`, hostname must be under a registered base domain) or `POST /api/homes/<slug>/proxy-mappings/tcp/` (raw TCP, using a public port from the home's dedicated TCP port range). The cloud allocates a free tunnel port from the home's range, updates the HAProxy map via the Runtime API, and returns the allocated port. No mapping state is persisted in the cloud database — HAProxy's live maps are the source of truth.
6. HAProxy routes incoming HTTPS traffic by SNI hostname, HTTP traffic by Host header, and TCP traffic by public port, to the matching tunnel backend.
7. Optionally, a home can set a per-home egress **bandwidth limit** (`PATCH /api/homes/<slug>/` with `bandwidth_limit_kbps`), enforced via `tc` HTB classes + `iptables` fwmark rules on the tunnel's outbound interface.

### Key design points

- **Privilege separation**: Django runs as the unprivileged `django` user. Tunnel management requires root; it is invoked via a tightly scoped sudoers rule (`docker/django/sudoers.d/tunneling`) that permits only the `manage_home.py` script.
- **Port allocation**: Each home slot gets a block of 10 SSH tunnel ports starting at `2000 + (home_index * 100)` (stride of 100 leaves headroom per home), plus a block of 10 dedicated public TCP ports starting at `10000 + (home_index * 10)` for raw TCP forwards.
- **Max homes**: 10 (indices 0–9), enforced in the `Home` model and in `manage_home.py`'s `Config`.
- **Username format**: `home<XX>_<django_username>` (e.g. `home00_alice`). The Django username is the SSH suffix.
- **Public keys** are staged to `/var/tunnelagent/public_keys/` before being passed to `manage_home.py`.
- **HAProxy routing**: tunnel backends are pre-created in `haproxy.cfg` for the full SSH port range and the TCP public port range. Three runtime map files drive routing: `sni_backends.map` (HTTPS SNI → backend), `host_http_backends.map` (HTTP Host → backend), `tcp_backends.map` (public TCP port → backend). All are updated at runtime via the HAProxy Runtime API on port 9999 and start empty on each container start; homes are responsible for re-registering their mappings after a restart.
- **Base domains**: a home must register a base domain (`HomeBaseDomain`) before it can create HTTP/HTTPS mappings for hostnames under it. `BaseDomainService` prevents one home from registering a domain that overlaps (as parent or subdomain) with another home's registered domain, and blocks domain removal while live HAProxy mappings still exist under it.
- **Bandwidth limiting**: `BandwidthManager` (in `manage_home.py`) creates an HTB class per home on the tunnel-facing interface and an `iptables` mangle rule that marks packets sourced from that home's SSH tunnel port range, so the limit applies regardless of which mapping/service is using the tunnel.
- **Home ownership**: `Home.user` is a FK to Django's `User` with `PROTECT` — a user cannot be deleted while they have assigned homes. A user may hold at most one home slot.
- **Reconciliation**: two idempotent management commands re-derive system state from the DB on startup — `reconcile_tunnel_users` (recreates missing Linux users/SSH config) and `reconcile_bandwidth` (re-applies `tc`/`iptables` bandwidth limits). There's also an admin-only `POST /api/admin/homes/sync` endpoint that does the same user-reconciliation on demand.
- **API tokens**: each home-owning user gets a DRF auth token (`HomeConfigService`), used by the home-side agent to call the cloud API. The web UI lets the user rotate this token, which invalidates the old one immediately.

### Source layout

```
cloud/
├── compose.yaml                          # Orchestrates haproxy + tunnelagent (django)
├── haproxy.dockerfile
├── django.dockerfile
├── docker/
│   ├── haproxy/
│   │   └── haproxy.cfg                   # HAProxy config (SNI/Host/TCP map routing, pre-created tunnel backends)
│   └── django/
│       ├── entrypoint.sh                 # Starts sshd + Django
│       └── sudoers.d/tunneling           # Sudo grant for manage_home.py
├── testsuite/                             # Standalone pytest suite (imports cloud/src via pythonpath)
│   └── tests/test_manage_home.py
└── src/
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
    │   │   └── reconcile_bandwidth.py     # Re-applies tc/iptables bandwidth limits on startup
    │   ├── tests/                         # Django-integrated tests for tunnel management
    │   └── ssh/
    │       └── manage_home.py             # Core tunnel user + bandwidth management script (TunnelManager, BandwidthManager)
    ├── api/                                # DRF REST API (thin layer over tunnels/)
    │   ├── views.py
    │   ├── serializers.py
    │   └── urls.py
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
| DELETE | `/api/homes/<slug>/` | Release a home slot |
| GET | `/api/homes/<slug>/base-domains/` | List base domains registered for this home |
| POST | `/api/homes/<slug>/base-domains/` | Register a base domain |
| DELETE | `/api/homes/<slug>/base-domains/<domain>/` | Remove a base domain (must have no active mappings under it) |
| GET | `/api/homes/<slug>/proxy-mappings/` | List caller's active HAProxy mappings (HTTP/HTTPS + TCP) |
| POST | `/api/homes/<slug>/proxy-mappings/<scheme>/` | Allocate a tunnel port and register an HTTP/HTTPS mapping (`scheme` = `http`/`https`, hostname must be under a registered base domain) |
| DELETE | `/api/homes/<slug>/proxy-mappings/<scheme>/<host>/` | Remove an HTTP/HTTPS forwarding rule from HAProxy |
| POST | `/api/homes/<slug>/proxy-mappings/tcp/` | Allocate a tunnel port and register a raw TCP mapping (public port must be in this home's TCP port range) |
| DELETE | `/api/homes/<slug>/proxy-mappings/tcp/<port>/` | Remove a TCP forwarding rule from HAProxy |
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current live HAProxy map entries (admin only) |
| POST | `/api/admin/homes/sync` | Reconcile DB homes with system users (admin only) |

Authentication is session-based (web UI) or token-based (`TokenAuthentication`, for the home-side agent). All endpoints require a logged-in user. Proxy mappings and base domains are scoped to the caller's own home slot.

### Web UI

Session-authenticated MVC views in `web/` (`web/views.py`, `web/forms.py`, `web/urls.py`) let a signed-up user register a home, view their dashboard (tunnel/proxy mapping status, generated `home/config.yaml`), rotate their API token, edit their SSH key, and release their home slot. `web/services.py`'s `HomeConfigService` renders the YAML config the home-side agent needs (cloud URL, auth token, SSH connection details, port ranges) and manages that user's DRF token lifecycle.

Note: `AddMappingView`/`DeleteMappingView` in `web/views.py` call `HAProxyService.add_mapping(host, tunnel_port, scheme)` and `HAProxyService.remove_mapping(host)`, but `HAProxyService` (in `tunnels/services.py`) now expects `add_mapping(scheme, tunnel_port, host=None, public_port=None)` and has no `remove_mapping` method (only `remove_http_mapping`/`remove_tcp_mapping`). These two views are currently broken/stale relative to the service layer — worth fixing or removing before relying on the manual "add mapping" web form.
