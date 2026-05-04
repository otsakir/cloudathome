# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CloudAtHome** enables home-hosted application servers to be reachable from the internet via a cloud proxy. The cloud server component manages SSH reverse tunnels and HAProxy routing rules. A home-side gateway (not yet in this repo) would connect to the cloud server to register and establish tunnels.

## Running & Building

All services run via Docker Compose from the `cloudserver/` directory:

```bash
# Build and start all services
docker compose -f cloudserver/compose.yaml up --build

# Start individual services
docker compose -f cloudserver/compose.yaml up tunnelagent
docker compose -f cloudserver/compose.yaml up haproxy
```

### Django (local development, outside Docker)

```bash
cd cloudserver/tunnelagent
source .venv/bin/activate
cd backend

# Run dev server
python manage.py runserver 0.0.0.0:8000

# Run all tests
python manage.py test

# Run a specific test module
python manage.py test external.tests

# Migrations
python manage.py makemigrations
python manage.py migrate
```

Use `DJANGO_SETTINGS_MODULE=backend.settings.local_settings` for local dev (SQLite, DEBUG=True). Docker uses `backend.settings.docker_settings`.

In local dev `HAPROXY_ENABLED=False` so HAProxy calls are skipped silently.

### Tunnel management script (requires sudo)

```bash
sudo python cloudserver/tunnelagent/backend/external/tunnels/manage_tunnel.py add <suffix> <home_id> -p <pubkey_file>
sudo python cloudserver/tunnelagent/backend/external/tunnels/manage_tunnel.py remove <suffix> <home_id>
sudo python cloudserver/tunnelagent/backend/external/tunnels/manage_tunnel.py reload
```

`add` and `remove` do not reload sshd automatically; `reload` must be called separately (as `ElevatedOperations` in `services.py` does).

## Architecture

### Components

| Component | Port(s) | Role |
|-----------|---------|------|
| **HAProxy** (cloud proxy) | 443 (HTTPS), 9999 (Runtime API) | SNI-based HTTPS ingress; routes traffic to per-home SSH tunnel ports via map file |
| **TunnelAgent** (Django + sshd) | 8000 (API), 8022 (SSH) | REST API for managing homes/proxy mappings; SSH server that accepts reverse tunnels from home networks |

### Request & tunnel flow

1. A home network registers by `POST /api/homes/` with its SSH public key.
2. Django calls `ElevatedOperations.add_home_user()` (in `external/services.py`), which sudo-executes `manage_tunnel.py`.
3. `manage_tunnel.py` creates a system user (`home<ID>_<username>`), installs the SSH key, and configures per-user `sshd` restrictions (TCP-forward only, no TTY/shell, allowed port range 2000–2099).
4. The home network's gateway then opens an SSH reverse tunnel on the assigned port.
5. A proxy mapping is created via `POST /api/proxy-mappings/`, which updates the HAProxy SNI map via the Runtime API socket — no reload needed.
6. HAProxy routes incoming HTTPS traffic by SNI hostname to the matching tunnel backend.

### Key design points

- **Privilege separation**: Django runs as the unprivileged `django` user. Tunnel management requires root; it is invoked via a tightly scoped sudoers rule (`/etc/sudoers.d/tunneling`) that permits only the `manage_tunnel.py` script.
- **Port allocation**: Each home slot gets a block of 10 ports starting at `2000 + (home_index * 100)`.
- **Max homes**: 10 (indices 0–9), enforced in the `Home` model.
- **Username format**: `home<XX>_<django_username>` (e.g. `home00_alice`). The Django username is the SSH suffix.
- **Public keys** are staged to `/var/tunnelagent/public_keys/` before being passed to `manage_tunnel.py`.
- **HAProxy routing**: 100 tunnel backends are pre-created in `haproxy.cfg` (one per port, ports 2000–2009, 2100–2109, … 2900–2909). SNI hostname → backend name mappings are stored in `sni_backends.map` and updated at runtime via the HAProxy Runtime API on port 9999. On Django startup, `api/apps.py` repopulates the map from the database.
- **Home ownership**: `Home.user` is a FK to Django's `User` with `PROTECT` — a user cannot be deleted while they have assigned homes.

### Source layout

```
cloudserver/
├── compose.yaml                          # Orchestrates haproxy + tunnelagent
├── haproxy.dockerfile
├── tunnelagent.dockerfile
├── docker/
│   ├── haproxy/
│   │   ├── haproxy.cfg                   # HAProxy config (SNI map routing, pre-created tunnel backends)
│   │   └── sni_backends.map              # Runtime SNI hostname → backend map (managed by Django)
│   └── tunnelagent/
│       ├── entrypoint.sh                 # Starts sshd + Django
│       └── sudoers.d/tunneling           # Sudo grant for manage_tunnel.py
└── tunnelagent/
    ├── requirements.txt
    └── backend/
        ├── manage.py
        ├── backend/settings/
        │   ├── local_settings.py
        │   └── docker_settings.py
        ├── api/                          # DRF app: models, views, serializers, urls
        │   ├── models.py                 # ProxyMapping, Home
        │   ├── apps.py                   # AppConfig; syncs HAProxy SNI map from DB on startup
        │   ├── views.py
        │   ├── serializers.py
        │   ├── urls.py
        │   ├── tests.py
        │   └── management/
        │       └── commands/
        │           └── reconcile_tunnel_users.py  # Recreates missing system users on startup
        └── external/
            ├── services.py               # ElevatedOperations (sudo wrapper)
            ├── haproxy.py                # HAProxy Runtime API client (set/del map via TCP socket)
            ├── tests/                    # Tests for external integrations
            └── tunnels/
                └── manage_tunnel.py      # Core tunnel user management script
```

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/homes/` | List caller's assigned homes (auth required) |
| POST | `/api/homes/` | Claim a home slot and install SSH key |
| DELETE | `/api/homes/<id>/` | Release a home slot |
| GET | `/api/proxy-mappings/` | List caller's proxy mappings (auth required) |
| POST | `/api/proxy-mappings/` | Create a forwarding rule and update HAProxy map |
| DELETE | `/api/proxy-mappings/<slug>/` | Remove a forwarding rule and update HAProxy map |
| POST | `/api/admin/proxy-mappings/sync` | Re-sync all DB mappings to HAProxy (admin only) |
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current HAProxy SNI map entries (admin only) |
| POST | `/api/admin/homes/sync` | Reconcile DB homes with system users (admin only) |

Authentication is session-based. All endpoints require a logged-in user. Proxy mappings are scoped to the caller's own homes.
