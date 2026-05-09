## About

A system that allows running application servers at home and access them from the internet.


## Overview

### Sites

* A `cloud server` running on any of the typical cloud providers. It is the entry point to the system for all https requests.
* A network of hosts behind NAT typically running at home. This is the `home network`

### Components

* **Cloud Proxy** - Main entry point to the system. It consists of a HAproxy application that listens on port 443 of the cloud server. It can be dynamically configured to 'forward' requests to local ports based on the request domain name (SNI). 

* **ProxyAgent** - An agent-like web service running on the cloud server that dynamically controls Cloud Proxy. It adds/removes forwarding mappings on demand. It offers a REST api to do that.

* **HomeGateway** - A linux machine plugged to the home network (behind NAT(s)) that represents the owner of the system and services and controls the overall operation of the system. It makes forwarding requests to the ProxyAgent running on the cloud server.  It sets up ssh tunnels from the cloud server to the home network. It contains a web app with UI to manage the system.

### How it works

  1. A home server registers with the cloud via a REST API, providing an SSH public key.
  2. The cloud creates a dedicated system user and SSH tunnel endpoint for that home.
  3. The home's gateway establishes an SSH reverse tunnel to the cloud server on an assigned port.
  4. The home creates a proxy mapping (hostname → tunnel port), which the cloud writes into HAProxy's SNI map at runtime.
  5. Incoming HTTPS traffic hits HAProxy on port 443, which routes it by SNI hostname through the tunnel to the home server — no cloud-side firewall changes, no reload needed.


## API

The ProxyAgent REST API is browsable via Swagger UI when running in debug mode:

- Swagger UI: `http://localhost:8000/api/schema/swagger/`
- ReDoc: `http://localhost:8000/api/schema/redoc/`
- OpenAPI schema (JSON): `http://localhost:8000/api/schema/`
- DRF login: http://localhost:8000/api-auth/login/


## Running with Docker

### Start the stack

```bash
docker compose -f cloudserver/compose.yaml up --build
```

This starts two services:
- **haproxy** — listens on port 443 (HTTPS ingress)
- **tunnelagent** — Django API on port 8000, SSH server on port 8022

HAProxy must pass its health check before tunnelagent starts. On first run, the `tunnelagent/var/` directory is created automatically as a bind-mounted volume for the SQLite database.

### First-time database setup

Run migrations and create a superuser:

```bash
docker compose -f cloudserver/compose.yaml exec tunnelagent python /opt/app/manage.py migrate
docker compose -f cloudserver/compose.yaml exec tunnelagent python /opt/app/manage.py createsuperuser
```

The SQLite database file is mapped outside of of the container at `./cloudserver/tunnelagent/var/db.sqlite3`.

### Provision home slots

The system supports up to 10 home slots (indices 0–9). The data migration `homes/migrations/0003_provision_homes.py` creates them automatically when you run `migrate`, so no extra step is needed.

### Create application users

Users can self-register at `http://localhost:8000/signup/`. New accounts are created inactive and must be approved by an administrator before login is allowed.

To activate an account, go to the Django admin UI at `http://localhost:8000/admin/`, open the user, tick **Active**, and save.

### Administration


#### Django administrator

Once the stack is running, you can access the Django administrator at the link below.

http://localhost:8000/admin/

#### Administrative endpoints

The following admin-only endpoints are also available (requires superuser session):

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/proxy-mappings/sync` | Re-sync all DB mappings to HAProxy |
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current HAProxy SNI map |
| POST | `/api/admin/homes/sync` | Reconcile DB homes with system SSH users |

---

## Home server

The `homeserver/` directory contains a minimal Docker Compose stack that simulates the home side: an nginx container serving a static "It works." page over HTTPS using a self-signed certificate. It is intended for local end-to-end testing.

```bash
docker compose -f homeserver/compose.yaml up --build
```

This starts nginx listening on `localhost:8443` (HTTPS). The self-signed certificate is generated at image build time, so there is no certificate file to manage.

---

## End-to-end walkthrough

This walkthrough runs both stacks on the same machine using `localhost` as the cloud address. Replace it with your actual cloud server hostname for a real deployment.

### 1. Start both stacks

In one terminal start the cloud stack:

```bash
docker compose -f cloudserver/compose.yaml up --build
```

In another terminal start the home server:

```bash
docker compose -f homeserver/compose.yaml up --build
```

### 2. Sign up

Go to `http://localhost:8000/signup/` and fill in the registration form. New accounts are created inactive.

### 3. Activate the account (admin step)

Log in to the Django admin at `http://localhost:8000/admin/` as the superuser. Open the new user, tick **Active**, and save.

### 4. Log in

Go to `http://localhost:8000/login/` and log in as alice. You are redirected to the dashboard at `http://localhost:8000/dashboard/`.

### 5. Register a home

From the dashboard, click **Register a home**. Paste your SSH public key (e.g. the contents of `~/.ssh/id_ed25519.pub`) into the form and submit.

The dashboard now shows the assigned **SSH username** (e.g. `home00_alice`) and **port base** (e.g. `2000`). Keep these values — they are needed for the next step.

### 6. Open the reverse SSH tunnel

From the home machine (or a separate terminal when testing locally), forward the cloud-side tunnel port to the home nginx:

```bash
ssh -N -T -R 127.0.0.1:2000:localhost:8443 home00_alice@localhost -p 8022
```

This maps **port 2000 on the cloud server** → **port 8443 on the home machine** (where nginx is listening). The command will appear to hang — that is correct; it is holding the tunnel open.

### 7. Add a proxy mapping

From the dashboard, click **Add mapping**. Fill in:

- **Hostname** — the public domain name that HAProxy will match by SNI (e.g. `mysite.example.com`)
- **Local port** — the tunnel port from step 5 (e.g. `2000`)
- **Scheme** — `https`

Submit the form. HAProxy's SNI map is updated immediately — no reload needed.

### 8. Test the full path

```bash
curl -k --resolve mysite.example.com:443:127.0.0.1 https://mysite.example.com
```

The `-k` flag accepts the home server's self-signed certificate. `--resolve` injects the hostname into the TLS ClientHello without needing a DNS entry, so HAProxy can match it by SNI.

You should see the "It works." page served by nginx on the home network.





