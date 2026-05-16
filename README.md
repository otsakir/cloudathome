## About

A system that allows running application servers at home and making them reachable from the internet via a cloud proxy — without opening any inbound firewall ports on the home network.


## Overview

### Sites

* A **cloud server** running on any typical cloud provider. It is the entry point for all HTTPS traffic.
* A **home network** — one or more hosts behind NAT that run the services you want to expose.

### Components

| Component | Location | Role |
|-----------|----------|------|
| **HAProxy** | Cloud server | SNI-based HTTPS ingress on port 443. Routes traffic to per-home SSH tunnel ports via a runtime-updated map file. |
| **Django + sshd** | Cloud server | REST API and web UI for managing homes and proxy mappings. SSH server that accepts reverse tunnels from home networks. |
| **Home Console** | Home network | Django app that manages domains, TLS certificates, and SSH reverse tunnels. Reads connection config from a local YAML file. |
| **Setup scripts** | Home network | Standalone scripts that generate an SSH key pair and register the home with the cloud server. Run once before starting the Home Console. |

### How it works

1. A home operator runs the setup scripts to generate an SSH key pair and register their home with the cloud server. The cloud server creates a dedicated system user and tunnel endpoint; the scripts write the resulting connection details to `home/config/cloudlink.yaml`.
2. The Home Console Django app is started. It reads `cloudlink.yaml` and is ready for use.
3. The operator adds a domain in the Home Console. The ACME flow runs automatically: a temporary SSH tunnel is opened, a proxy mapping is registered on the cloud server, Let's Encrypt issues a certificate via HTTP-01 challenge, then the temporary tunnel and mapping are torn down.
4. The operator adds an HTTPS proxy entry for the domain and opens its SSH reverse tunnel. HAProxy's SNI map is updated immediately — no reload needed.
5. Incoming HTTPS traffic hits HAProxy on port 443, which routes it by SNI hostname through the tunnel to the home service.


## Cloud server

### Running with Docker

```bash
docker compose -f cloud/compose.yaml up --build
```

This starts two containers:
- **haproxy** — listens on ports 80 and 443
- **tunnelagent** — Django API on port 8000, SSH server on port 8022

HAProxy must pass its health check before `tunnelagent` starts.

### First-time database setup

```bash
docker compose -f cloud/compose.yaml exec tunnelagent python /opt/app/manage.py migrate
docker compose -f cloud/compose.yaml exec tunnelagent python /opt/app/manage.py createsuperuser
```

The SQLite database is stored outside the container at `cloud/django/var/db.sqlite3`.

The `migrate` step also provisions the 10 home slots (indices 0–9) automatically via the data migration `homes/migrations/0003_provision_homes.py`.

### User accounts

Users self-register at `http://<cloud-host>:8000/signup/`. New accounts are created **inactive** and must be approved by an administrator before login is allowed.

To activate an account: go to the Django admin at `http://<cloud-host>:8000/admin/`, open the user, tick **Active**, and save.

### REST API

The API is browsable via Swagger UI when running in debug mode:

- Swagger UI: `http://localhost:8000/api/schema/swagger/`
- ReDoc: `http://localhost:8000/api/schema/redoc/`
- OpenAPI schema: `http://localhost:8000/api/schema/`

#### Admin-only endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/proxy-mappings/sync` | Re-sync all DB mappings to HAProxy |
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current live HAProxy SNI map |
| POST | `/api/admin/homes/sync` | Reconcile DB homes with system SSH users |

---

## Home system

The `home/` directory contains everything needed to connect a home network to the cloud server.

```
home/
├── config/
│   ├── cloudlink.yaml          # written by register_home.py — contains secrets, not committed
│   └── cloudlink.yaml.example  # template showing all required fields
├── scripts/
│   ├── generate_keys.py        # generate a dedicated SSH key pair for tunnel use
│   └── register_home.py        # register with the cloud server, write cloudlink.yaml
└── django/                     # Home Console Django app
    ├── cloudlink/              # config loading, cloud API client, dashboard
    └── domains/                # domain, certificate, and tunnel management
```

### Prerequisites

- Python 3.11+
- Docker (required for certificate issuance)
- A registered account on the cloud server (see [User accounts](#user-accounts) above)
- The `cloudathome-acme` Docker image — build it once:

```bash
docker build -t cloudathome-acme -f home/nginx.dockerfile home/
```

### Step 1 — Generate an SSH key pair

Run this once on the home machine. It creates a dedicated key pair for CloudAtHome tunnel use and prints the public key.

```bash
python home/scripts/generate_keys.py
```

By default the private key is written to `~/.ssh/cloudathome_ed25519`. Use `--output` to choose a different path:

```bash
python home/scripts/generate_keys.py --output /path/to/key
```

Use `--force` to overwrite an existing key pair.

### Step 2 — Register the home with the cloud server

This script authenticates with the cloud server, claims a home slot, and writes the connection config to `home/config/cloudlink.yaml`.

```bash
python home/scripts/register_home.py \
    --cloudserver-url https://cloud.example.com \
    --username alice \
    --password secret \
    --public-key ~/.ssh/cloudathome_ed25519.pub \
    --private-key ~/.ssh/cloudathome_ed25519
```

On success it prints a summary:

```
Done. Configuration written to: home/config/cloudlink.yaml
  home_slug    : xK3mAbcDef9pQr
  ssh_username : home02_alice
  ssh_host     : cloud.example.com:22
  port range   : 2200 – 2209
```

The generated `cloudlink.yaml` contains secrets (auth token, key path) and is gitignored. See `home/config/cloudlink.yaml.example` for the full schema.

### Step 3 — Install dependencies and run the Home Console

```bash
cd home/django
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

The Home Console is available at `http://localhost:8001/`. Django reads `cloudlink.yaml` at startup. If the file is missing or malformed, startup fails immediately with a clear error message.

> **Changing the config path:** Set the `CLOUDLINK_CONFIG` environment variable to an absolute path if you want to keep `cloudlink.yaml` somewhere other than `home/config/`.

### Obtaining a TLS certificate

Go to **Domains → Add domain** and fill in:

- **Domain name** — the public domain (e.g. `mysite.example.com`). DNS must already point to the cloud server.
- **Email address** — used by Let's Encrypt for renewal notifications.
- **Certificate output directory** — absolute path on this machine where certificates will be stored (e.g. `/etc/cloudathome/certs`).

Submitting triggers the ACME flow automatically:

1. A free tunnel port is allocated from the home's assigned range.
2. A temporary HTTP proxy mapping is registered on the cloud server.
3. An SSH reverse tunnel is opened to that port.
4. The `cloudathome-acme` container starts; certbot performs the HTTP-01 challenge.
5. The tunnel and mapping are torn down; the container is removed.
6. The domain is updated with the certificate path and expiry date.

### Exposing a service (HTTPS proxy entry)

After a certificate exists for a domain, go to the domain detail page and click **Add HTTPS proxy entry**. Fill in:

- **Public hostname** — the domain HAProxy will route (usually the same as the domain name).
- **Home port** — the local port your service listens on (e.g. `443`).

This creates the cloud proxy mapping. The tunnel is not opened automatically — click **Open tunnel** on the proxy entry to start it.

### Managing tunnels

Each proxy entry on the domain detail page has an **Open tunnel / Close tunnel** button. Tunnels are OS-level SSH processes; their PIDs are stored in the database so they can be stopped cleanly even after a Django restart.

---

## End-to-end walkthrough

This walkthrough goes from a fresh cloud stack to a publicly reachable home service. It assumes the cloud server has a public IP and that `mysite.example.com` DNS points to it.

### 1. Start the cloud stack

```bash
docker compose -f cloud/compose.yaml up --build
```

### 2. Create and activate a cloud account

Go to `http://<cloud-host>:8000/signup/` and register. Log in to the Django admin at `http://<cloud-host>:8000/admin/` as the superuser, open the new user, tick **Active**, and save.

### 3. Generate an SSH key pair (home machine)

```bash
python home/scripts/generate_keys.py
# prints the public key; private key written to ~/.ssh/cloudathome_ed25519
```

### 4. Register the home (home machine)

```bash
python home/scripts/register_home.py \
    --cloudserver-url http://<cloud-host>:8000 \
    --username alice \
    --password secret \
    --public-key ~/.ssh/cloudathome_ed25519.pub \
    --private-key ~/.ssh/cloudathome_ed25519
```

This writes `home/config/cloudlink.yaml` with the assigned SSH username, port range, and auth token.

### 5. Start the Home Console

```bash
docker build -t cloudathome-acme -f home/nginx.dockerfile home/   # first time only
cd home/django && source .venv/bin/activate
python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

### 6. Obtain a TLS certificate

Go to `http://localhost:8001/domains/add/`. Enter `mysite.example.com`, your email, and a local cert path (e.g. `/etc/cloudathome/certs`). Submit and wait — the ACME flow runs automatically.

### 7. Add an HTTPS proxy entry

From the domain detail page click **Add HTTPS proxy entry**. Set the hostname to `mysite.example.com` and the home port to the port your service listens on (e.g. `443`).

### 8. Open the tunnel

Click **Open tunnel** on the proxy entry.

### 9. Test

```bash
curl https://mysite.example.com
```

Traffic hits HAProxy on the cloud server, is routed by SNI through the SSH tunnel, and arrives at your home service.

---

## Manual testing walkthrough

This walkthrough exercises the cloud stack locally — no real domain or DNS needed. It manually opens an SSH tunnel and adds a proxy mapping via the cloud web UI, without using the Home Console at all.

### 1. Start the cloud stack

```bash
docker compose -f cloud/compose.yaml up --build
```

### 2. Sign up and activate an account

Go to `http://localhost:8000/signup/` and register. Log in to the Django admin at `http://localhost:8000/admin/` as the superuser, open the new user, tick **Active**, and save.

### 3. Register a home via the cloud web UI

Go to `http://localhost:8000/login/`. From the dashboard click **Register a home**, paste your SSH public key (e.g. the contents of `~/.ssh/id_ed25519.pub`), and submit.

Note the assigned **SSH username** (e.g. `home00_alice`) and **port base** (e.g. `2000`).

### 4. Start a local service to expose

```bash
docker build -t cloudathome-home-sim -f home/nginx.dockerfile home/
docker run --rm -p 8443:80 cloudathome-home-sim
```

This starts nginx on `localhost:8443`.

### 5. Open the reverse SSH tunnel manually

```bash
ssh -N -T -R 127.0.0.1:2000:localhost:8443 home00_alice@localhost -p 8022
```

This forwards **port 2000 on the cloud server** → **port 8443 on this machine**. The command hangs — that is correct; it holds the tunnel open.

### 6. Add a proxy mapping via the cloud web UI

From the cloud dashboard click **Add mapping** and fill in:

- **Hostname** — any domain (e.g. `mysite.example.com`)
- **Tunnel port** — the port base from step 3 (e.g. `2000`)
- **Scheme** — `https`

HAProxy's SNI map is updated immediately.

### 7. Test

```bash
curl -k --resolve mysite.example.com:443:127.0.0.1 https://mysite.example.com
```

`--resolve` injects the hostname into the TLS ClientHello without a real DNS entry. `-k` accepts the self-signed certificate. You should see the response from the local service.
