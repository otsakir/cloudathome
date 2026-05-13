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
docker compose -f cloud/compose.yaml up --build
```

This starts two services:
- **haproxy** — listens on port 443 (HTTPS ingress)
- **tunnelagent** — Django API on port 8000, SSH server on port 8022

HAProxy must pass its health check before tunnelagent starts. On first run, the `django/var/` directory is created automatically as a bind-mounted volume for the SQLite database.

### First-time database setup

Run migrations and create a superuser:

```bash
docker compose -f cloud/compose.yaml exec tunnelagent python /opt/app/manage.py migrate
docker compose -f cloud/compose.yaml exec tunnelagent python /opt/app/manage.py createsuperuser
```

The SQLite database file is mapped outside of of the container at `./cloud/django/var/db.sqlite3`.

### Provision home slots

The system supports up to 10 home slots (indices 0–9). The data migration `homes/migrations/0003_provision_homes.py` creates them automatically when you run `migrate`, so no extra step is needed.

### Create application users

Users can self-register at `http://localhost:8000/signup/`. New accounts are created **inactive** and must be approved by an administrator before login is allowed.

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

## Home system

The `home/` directory contains the home-side Django application. It connects to the cloud server, manages TLS certificates via Let's Encrypt, and controls SSH reverse tunnels — all through a web UI.

### Components

| Path | Role |
|------|------|
| `home/django/` | Django project |
| `home/django/cloudlink/` | Cloud connection setup (credentials, setup wizard) |
| `home/django/domains/` | Domain, certificate and tunnel management |
| `home/nginx.dockerfile` | nginx + certbot image used for ACME certificate issuance |

### Prerequisites

- Python 3.11+
- Docker (required for certificate issuance)
- An SSH key pair — the public key is registered with the cloud server; the private key path is entered during setup
- The `cloudathome-acme` Docker image must be built before issuing any certificates:

```bash
docker build -t cloudathome-acme -f home/nginx.dockerfile home/
```

### Running locally

```bash
cd home/django
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

The home console is available at `http://localhost:8001/`.

### First-time setup

On first visit you are redirected to the setup wizard at `/setup/`. Fill in:

- **CloudServer URL** — base URL of the cloud server (e.g. `https://cloud.example.com`)
- **Username / Password** — your account on the cloud server
- **SSH public key** — contents of the public key to register with the cloud (e.g. `~/.ssh/id_ed25519.pub`)
- **SSH private key path** — absolute path to the matching private key on this machine
- **SSH port** — SSH port of the cloud server (default 22)

Submitting the form authenticates with the cloud, registers the home, and saves the connection config.

### Obtaining a TLS certificate

Go to **Domains → Add domain** and fill in:

- **Domain name** — the public domain name (e.g. `mysite.example.com`). DNS must already point to the cloud server.
- **Email address** — used by Let's Encrypt for renewal notifications
- **Certificate output directory** — absolute path on this machine where certificates will be stored

Submitting kicks off the full ACME flow automatically:
1. A temporary HTTP tunnel is opened to the cloud server
2. A temporary cloud proxy mapping routes port-80 traffic for the domain through the tunnel
3. The `cloudathome-acme` container starts and certbot obtains the certificate
4. The tunnel and mapping are torn down
5. The domain is updated with the certificate path and expiry

### Exposing a service

After a certificate is issued, go to the domain detail page and click **Add HTTPS proxy entry**. Fill in:

- **Public hostname** — the domain name HAProxy will route (usually the same as the domain)
- **Home port** — the port of the local service (e.g. `443`)

This creates a cloud proxy mapping. The SSH tunnel is managed separately — click **Open tunnel** on the proxy entry to start it.

### Managing tunnels

Each proxy entry on the domain detail page has an **Open tunnel / Close tunnel** button. Tunnels are OS-level SSH processes; their PIDs are stored in the database so they can be stopped even after a Django restart.

---

## End-to-end walkthrough

This walkthrough shows the full flow from a fresh cloud stack to a publicly reachable home service. It assumes the cloud server has a public IP with DNS entries pointing `mysite.example.com` to it.

### 1. Start the cloud stack

```bash
docker compose -f cloud/compose.yaml up --build
```

### 2. Create a cloud account

Go to `http://<cloud-host>:8000/signup/` and register. New accounts are inactive by default.

Log in to the Django admin at `http://<cloud-host>:8000/admin/` as the superuser, open the new user, tick **Active**, and save.

### 3. Run the home console

On the home machine:

```bash
docker build -t cloudathome-acme -f home/nginx.dockerfile home/
cd home/django && source .venv/bin/activate
python manage.py runserver 0.0.0.0:8001
```

### 4. Run the setup wizard

Go to `http://localhost:8001/setup/` and fill in the cloud server URL, credentials, and SSH key details. The home is registered with the cloud server on submit.

### 5. Obtain a certificate

Go to `http://localhost:8001/domains/add/`. Enter `mysite.example.com`, your email, and a local path for the certificates (e.g. `/etc/cloudathome/certs`). Submit and wait — the ACME flow runs automatically.

### 6. Add an HTTPS proxy entry

From the domain detail page, click **Add HTTPS proxy entry**. Set the hostname to `mysite.example.com` and the home port to the port your service listens on (e.g. `443`).

### 7. Open the tunnel

Click **Open tunnel** on the proxy entry. The SSH reverse tunnel to the cloud server is now active.

### 8. Test

```bash
curl https://mysite.example.com
```

Traffic hits HAProxy on the cloud server, is routed through the SSH tunnel by SNI, and arrives at your home service.

---

## Manual testing walkthrough

This walkthrough exercises the cloud stack locally — no real domain or DNS needed. It manually opens the SSH tunnel and adds a proxy mapping via the cloud web UI, bypassing the home Django app entirely.

### 1. Start the cloud stack

```bash
docker compose -f cloud/compose.yaml up --build
```

### 2. Sign up and activate an account

Go to `http://localhost:8000/signup/` and register. Log in to the Django admin at `http://localhost:8000/admin/` as the superuser, open the new user, tick **Active**, and save.

### 3. Log in and register a home

Go to `http://localhost:8000/login/`. From the dashboard click **Register a home**, paste your SSH public key (e.g. `~/.ssh/id_ed25519.pub`), and submit.

Note the assigned **SSH username** (e.g. `home00_alice`) and **port base** (e.g. `2000`).

### 4. Start a local service to expose

Start anything that listens on a local port. For a quick test, the old nginx simulation image works:

```bash
docker build -t cloudathome-home-sim -f home/nginx.dockerfile home/
docker run --rm -p 8443:443 cloudathome-home-sim
```

This starts nginx on `localhost:8443`.

### 5. Open the reverse SSH tunnel manually

```bash
ssh -N -T -R 127.0.0.1:2000:localhost:8443 home00_alice@localhost -p 8022
```

This forwards **port 2000 on the cloud server** → **port 8443 on this machine**. The command hangs — that is correct; it is holding the tunnel open.

### 6. Add a proxy mapping

From the cloud dashboard click **Add mapping** and fill in:

- **Hostname** — any fake domain (e.g. `mysite.example.com`)
- **Tunnel port** — the port base from step 3 (e.g. `2000`)
- **Scheme** — `https`

HAProxy's SNI map is updated immediately.

### 7. Test

```bash
curl -k --resolve mysite.example.com:443:127.0.0.1 https://mysite.example.com
```

`--resolve` injects the hostname into the TLS ClientHello without a real DNS entry. `-k` accepts the self-signed certificate. You should see the response from the local service.





