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

1. A home operator runs the setup scripts to generate an SSH key pair and register their home with the cloud server. The cloud server creates a dedicated system user and tunnel endpoint; the scripts write the resulting connection details to `home/config.yaml`.
2. The Home Console Django app is started. It reads `config.yaml` and is ready for use.
3. The operator adds a domain and a proxy entry in the Home Console. The proxy entry registers the cloud proxy mapping and records the allocated tunnel port.
4. The operator opens the SSH tunnel and triggers certificate issuance from the proxy entry page. Certbot runs standalone locally; Let's Encrypt validates via the tunnel. The certificate is stored under `home/certbot/`.
5. The operator closes the temporary tunnel if needed, or keeps it open for production traffic.
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
├── config.yaml              # written by register_home.py — contains secrets, not committed
├── config.yaml.example      # template showing all required fields
├── certbot/                 # created on first certificate issuance, gitignored
│   ├── config/              # certbot config and issued certificates
│   ├── work/                # certbot working directory
│   └── logs/                # certbot logs
├── scripts/
│   ├── generate_keys.py     # generate a dedicated SSH key pair for tunnel use
│   └── register_home.py     # register with the cloud server, write config.yaml
└── django/                  # Home Console Django app
    ├── cloudlink/           # config loading, cloud API client, dashboard
    └── domains/             # domain, certificate, and tunnel management
```

### Prerequisites

- Python 3.11+
- `certbot` CLI installed on the home machine (e.g. `sudo apt install certbot` or `pip install certbot`)
- A registered account on the cloud server (see [User accounts](#user-accounts) above)

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

This script authenticates with the cloud server, claims a home slot, and writes the connection config to `home/config.yaml`.

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
Done. Configuration written to: home/config.yaml
  home_slug    : xK3mAbcDef9pQr
  ssh_username : home02_alice
  ssh_host     : cloud.example.com:22
  port range   : 2200 – 2209
```

The generated `config.yaml` contains secrets (auth token, key path) and is gitignored. See `home/config.yaml.example` for the full schema.

### Step 3 — Install dependencies and run the Home Console

```bash
cd home/django
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

The Home Console is available at `http://localhost:8001/`. Django reads `config.yaml` at startup. If the file is missing or malformed, startup fails immediately with a clear error message.

> **Changing the config path:** Set the `CLOUDATHOME_CONFIG` environment variable to an absolute path if you want to keep `config.yaml` somewhere other than `home/`.

### Obtaining a TLS certificate

Certificate issuance is tied to a proxy entry. The full sequence from the Home Console:

**1. Add a domain** — go to **Domains → Add domain** and enter the domain name (e.g. `mysite.example.com`). DNS must already point to the cloud server.

**2. Add a proxy entry** — from the domain detail page click **Add**. Choose a scheme and the local port certbot will listen on (e.g. `8082`). This registers the proxy mapping on the cloud server; the tunnel port is allocated server-side.

**3. Open the tunnel** — on the proxy entry detail page click **Open tunnel**. This starts an SSH reverse tunnel: `cloud_tunnel_port → home:home_port`.

**4. Issue the certificate** — with the tunnel open, enter your email and click **Issue certificate**. Certbot runs in standalone mode, Let's Encrypt validates the HTTP-01 challenge through the tunnel, and the certificate is saved to `home/certbot/config/live/<domain>/`.

The domain record is updated with the certificate path and expiry date on success.

### Managing tunnels

Each proxy entry detail page has an **Open tunnel / Close tunnel** button. Tunnels are OS-level SSH processes; their PIDs are stored in the database so they can be stopped cleanly even after a Django restart. If a tunnel process dies unexpectedly, the status is corrected automatically the next time the proxy entry page is loaded.

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

This writes `home/config.yaml` with the assigned SSH username, port range, and auth token.

### 5. Start the Home Console

```bash
cd home/django && source .venv/bin/activate
python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

### 6. Add a domain and proxy entry

Go to `http://localhost:8001/domains/add/` and enter `mysite.example.com`. From the domain detail page click **Add** to create a proxy entry — choose scheme `http` and the port certbot will listen on (e.g. `8082`).

### 7. Open the tunnel and obtain a TLS certificate

From the proxy entry detail page click **Open tunnel**, then enter your email and click **Issue certificate**. Wait for certbot to complete — the domain record is updated with the cert path on success.

### 8. Open the tunnel for production traffic

Click **Open tunnel** on the proxy entry (if you closed it after cert issuance).

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
docker run --rm -p 8443:80 nginx
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
