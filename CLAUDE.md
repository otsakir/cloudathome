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

### Tunnel management script (requires sudo)

```bash
sudo python cloudserver/tunnelagent/backend/external/tunnels/manage_tunnel.py add <suffix> <home_id> -p <pubkey_file>
sudo python cloudserver/tunnelagent/backend/external/tunnels/manage_tunnel.py remove <suffix> <home_id>
```

## Architecture

### Components

| Component | Port(s) | Role |
|-----------|---------|------|
| **HAProxy** (cloud proxy) | 443 (HTTPS), 5556 (DataPlane API) | SNI-based HTTPS ingress; routes traffic to per-home SSH tunnel ports |
| **TunnelAgent** (Django + sshd) | 8000 (API), 8022 (SSH) | REST API for managing homes/proxy mappings; SSH server that accepts reverse tunnels from home networks |

### Request & tunnel flow

1. A home network registers by `POST /api/homes/` with its SSH public key.
2. Django calls `ElevatedOperations.add_home_user()` (in `external/services.py`), which sudo-executes `manage_tunnel.py`.
3. `manage_tunnel.py` creates a system user (`home<ID>_<suffix>`), installs the SSH key, and configures per-user `sshd` restrictions (TCP-forward only, no TTY/shell, allowed port range 2000–2099).
4. The home network's gateway then opens an SSH reverse tunnel on the assigned port.
5. HAProxy is configured (via its DataPlane API) to forward matching HTTPS traffic into that tunnel port.

### Key design points

- **Privilege separation**: Django runs as the unprivileged `django` user. Tunnel management requires root; it is invoked via a tightly scoped sudoers rule (`/etc/sudoers.d/tunneling`) that permits only the `manage_tunnel.py` script.
- **Port allocation**: Each home slot gets a block of 10 ports starting at `2000 + (home_index * 100)`.
- **Max homes**: 10 (indices 0–9), enforced in the `Home` model.
- **Username format**: `home<XX>_<suffix>` (e.g. `home00_alice`). Suffix is 1–20 alphanumeric/`_`/`-` chars.
- **Public keys** are staged to `/var/tunnelagent/public_keys/` before being passed to `manage_tunnel.py`.

### Source layout

```
cloudserver/
├── compose.yaml                          # Orchestrates haproxy + tunnelagent
├── haproxy.dockerfile
├── tunnelagent.dockerfile
├── docker/
│   ├── haproxy/haproxy.cfg               # HAProxy config (DataPlane API, SNI routing)
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
        │   ├── views.py
        │   ├── serializers.py
        │   └── urls.py
        ├── external/
        │   ├── services.py               # ElevatedOperations (sudo wrapper)
        │   └── tunnels/
        │       └── manage_tunnel.py      # Core tunnel user management script
        └── tunnels/                      # Django app stub (in progress)
```

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/homes/` | List assigned homes (auth required) |
| POST | `/api/homes/` | Claim a home slot and install SSH key |
| DELETE | `/api/homes/<id>/` | Release a home slot |
| GET | `/api/proxy-mappings/` | List HAProxy forwarding rules |
| POST | `/api/proxy-mappings/` | Create a forwarding rule |
| DELETE | `/api/proxy-mappings/<slug>/` | Remove a forwarding rule |

Authentication is session-based. Home endpoints require a logged-in user.
