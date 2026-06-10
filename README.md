## About

A system that allows running application servers at home and making them reachable from the internet via a cloud proxy — without opening any inbound firewall ports on the home network.


## Overview

### Sites

* A **cloud server** running on any typical cloud provider. It is the entry point for all HTTPS traffic.
* A **home network** — one or more hosts behind NAT that run the services you want to expose.

### Components

| Component | Location | Role |
|-----------|----------|------|
| **HAProxy** | Cloud server | HTTPS ingress on port 443 (SNI-based routing) and TCP forwarding on ports 10000–10099 (port-based routing). Routes traffic to per-home SSH tunnel ports via runtime-updated map files. |
| **Django + sshd** | Cloud server | REST API and web UI for managing homes and proxy mappings. SSH server that accepts reverse tunnels from home networks. |
| **Home Console** | Home network | Django app that manages HTTP/HTTPS forwards (domain + TLS certificate lifecycle), TCP forwards, and SSH reverse tunnels. Reads connection config from a local YAML file. |
| **Setup scripts** | Home network | Standalone scripts that generate an SSH key pair and register the home with the cloud server. Run once before starting the Home Console. |

### How it works

1. A home operator runs the setup scripts to generate an SSH key pair and register their home with the cloud server. The cloud server creates a dedicated system user and tunnel endpoint; the scripts write the resulting connection details to `home/config.yaml`.
2. The Home Console Django app is started. It reads `config.yaml` and is ready for use.
3. For HTTP/HTTPS forwards, the operator first registers one or more **base domains** with the cloud server (e.g. `mysite.example.com`). The cloud enforces that no two homes can claim overlapping domains. The home is then authoritative for that domain and all its subdomains.
4. The operator adds forwards in the Home Console — either HTTP/HTTPS (domain-based) or TCP (port-based). Each forward registers a mapping directly in HAProxy on the cloud server (no persistent cloud-side state) and records the allocated tunnel port locally. HTTP/HTTPS forwards are only accepted if the hostname falls under one of the home's registered base domains.
5. For HTTP/HTTPS forwards: the operator opens the SSH tunnel and triggers certificate issuance from the proxy entry page. Certbot runs standalone locally; Let's Encrypt validates via the tunnel. The certificate is stored under `home/certbot/`.
6. The operator closes the temporary tunnel if needed, or keeps it open for production traffic.
7. Incoming HTTPS traffic hits HAProxy on port 443, routed by SNI hostname through the tunnel. Incoming TCP traffic hits HAProxy on the allocated public port (10000–10099), routed by destination port through the tunnel.


## Cloud server

### Running (Docker only)

```bash
docker compose -f cloud/compose.yaml up --build
```

This starts two containers:
- **haproxy** — listens on ports 80 and 443 (HTTP/HTTPS) and 10000–10099 (TCP forwards)
- **tunnelagent** — Django API on port 8000, SSH server on port 8022

HAProxy must pass its health check before `tunnelagent` starts.

Swagger URL

```commandline
http://localhost:8000/api/schema/swagger/
```

Django administrator

```commandline
http://localhost:8000/admin/login/
```


### First-time database setup

```bash
docker compose -f cloud/compose.yaml exec tunnelagent python /opt/app/manage.py migrate
docker compose -f cloud/compose.yaml exec tunnelagent python /opt/app/manage.py createsuperuser
```

The SQLite database is stored outside the container at `cloud/src/var/db.sqlite3`.

The `migrate` step also provisions the 10 home slots (indices 0–9) automatically via the data migration `tunnels/migrations/0003_provision_homes.py`.

### User accounts

Users self-register at `http://<cloud-host>:8000/signup/`. New accounts are created **inactive** and must be approved by an administrator before login is allowed.

To activate an account: go to the Django admin at `http://<cloud-host>:8000/admin/`, open the user, tick **Active**, and save.

### REST API

The API is browsable via Swagger UI when running in debug mode:

- Swagger UI: `http://localhost:8000/api/schema/swagger/`
- ReDoc: `http://localhost:8000/api/schema/redoc/`
- OpenAPI schema: `http://localhost:8000/api/schema/`

#### Home endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/homes/` | List caller's assigned homes |
| POST | `/api/homes/` | Claim a home slot and install SSH key |
| GET | `/api/homes/<slug>/` | Retrieve home details (port ranges, base domains, bandwidth limit) |
| PATCH | `/api/homes/<slug>/` | Update SSH public key or bandwidth limit |
| DELETE | `/api/homes/<slug>/` | Release a home slot |
| GET | `/api/homes/<slug>/base-domains/` | List registered base domains |
| POST | `/api/homes/<slug>/base-domains/` | Register a base domain |
| DELETE | `/api/homes/<slug>/base-domains/<domain>/` | Remove a base domain (blocked if active proxy mappings exist under it) |
| GET | `/api/homes/<slug>/proxy-mappings/` | List active HAProxy mappings for this home |
| POST | `/api/homes/<slug>/proxy-mappings/` | Allocate a tunnel port and register in HAProxy |
| DELETE | `/api/homes/<slug>/proxy-mappings/<key>/` | Remove a forwarding rule from HAProxy |

#### Admin-only endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current live HAProxy map entries |
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

> **Changing the config path:** Set the `HOME_CONFIG` environment variable to point at a different `config.yaml` if you want to keep it somewhere other than `home/`.

### Portability

The entire home-side state lives in four portable pieces:

| Piece | Default location | Configured by |
|-------|-----------------|---------------|
| Connection config | `home/config.yaml` | `HOME_CONFIG` env var |
| Database | `home/db.sqlite3` | `database` in config.yaml |
| TLS certificates | `home/certbot/` | certbot working directory |
| SSH key pair | `~/.ssh/cloudathome_ed25519` | `--private-key` / `ssh.private_key_path` |

To move the Home Console to another machine: copy those four items, update any absolute paths in `config.yaml`, and run `python manage.py runserver` as usual.

To switch between cloud servers (e.g. dev vs production), keep a separate `config.yaml` for each — with its own `database.path` — and select the active one with `HOME_CONFIG`:

```bash
# production
python manage.py runserver 0.0.0.0:8001

# dev cloud
HOME_CONFIG=home/config-dev.yaml python manage.py runserver 0.0.0.0:8001
```

### Base domains

Before creating any HTTP/HTTPS proxy entry, the home must register at least one base domain with the cloud server. A base domain is a domain the operator controls in DNS — the cloud server enforces that no two homes can claim the same domain or overlapping domains (e.g. if Home A owns `example.com`, Home B cannot register `sub.example.com`).

The cloud validates that the domain is a proper registrable domain (not a bare TLD like `com` or a public suffix like `co.uk`) using the Public Suffix List.

**From the Home Console dashboard:**
- Click **Register base domain**, enter the domain name, and submit.
- The domain is stored on the cloud server and returned in the home's info response.
- To remove a domain, click **Remove** next to it on the dashboard. This is blocked with an error if any active proxy mappings still use that domain or its subdomains — disconnect those mappings first.

A home can register multiple base domains. Subdomains do not need to be registered separately — once `example.com` is registered, the home can freely create proxy entries for `blog.example.com`, `api.example.com`, etc.

### Obtaining a TLS certificate

Certificate issuance is tied to a proxy entry. The full sequence from the Home Console:

**1. Add a domain** — go to **Domains → Add domain** and enter the domain name (e.g. `mysite.example.com`). DNS must already point to the cloud server.

**2. Add a proxy entry** — from the domain detail page click **Add**. Choose a scheme and the local port certbot will listen on (e.g. `8082`). This registers the proxy mapping on the cloud server; the tunnel port is allocated server-side.

**3. Open the tunnel** — on the proxy entry detail page click **Open tunnel**. This starts an SSH reverse tunnel: `cloud_tunnel_port → home:home_port`.

**4. Issue the certificate** — with the tunnel open, click **Issue certificate**. Enter your email on the certificate page and submit. Certbot runs in standalone mode, Let's Encrypt validates the HTTP-01 challenge through the tunnel, and the certificate is saved to `home/certbot/config/live/<domain>/`.

The domain record is updated with the certificate path and expiry date on success.

### Bandwidth throttling

Per-home bandwidth limits cap how much of the home's internet upload the cloud tunnel can consume. Limits are enforced on the cloud server using Linux `tc` (HTB) and `iptables`; TCP backpressure through the SSH connection naturally bounds the home-side upload rate.

#### How enforcement works

When a limit is set the cloud server runs the following for the home's assigned port range:

```
tc qdisc add dev eth0 root handle 1: htb default 999
tc class add dev eth0 parent 1: classid 1:<N> htb rate <X>kbit ceil <X>kbit
tc filter add dev eth0 parent 1: handle <N> fw classid 1:<N>
iptables -t mangle -A OUTPUT -p tcp --sport <port_low>:<port_high> -j MARK --set-mark <N>
```

All egress TCP traffic sourced from the home's tunnel port range is marked, then shaped through the HTB leaf class at the configured rate. Unrelated traffic is unaffected.

#### Reconciliation on restart

On container start the `reconcile_bandwidth` management command re-applies all limits from the database, since `tc` and `iptables` rules do not survive a container restart.

#### API

A home owner sets or clears the limit via `PATCH /api/homes/<slug>/`:

```
PATCH /api/homes/<slug>/
{"bandwidth_limit_kbps": 5000}   # set to 5 Mbit/s
{"bandwidth_limit_kbps": null}   # remove limit (unlimited)
```

Accepted range: 100 – 10,000,000 kbps. `null` means unlimited.

---

### Managing tunnels

Tunnels are OS-level SSH processes. Their PIDs are stored in the database so they can be stopped cleanly even after a Django restart. If a tunnel process dies unexpectedly, the status is corrected automatically the next time the proxy entry page is loaded.

SSH process output (stdout/stderr) is inherited from the Django process and appears directly in the Home Console's terminal. For example, if the local service is not yet listening on its port, you will see repeated `connect_to localhost port <N>: failed.` lines — these come from SSH, not Django.

**Per-entry controls** (proxy entry detail page):
- **Open tunnel / Close tunnel** — manually open or close a single tunnel.
- **Sync** — idempotent reconnect: re-registers the cloud proxy mapping and reopens the tunnel if it is not running. Use this to recover a single entry after a crash or restart.

**Global controls** (dashboard):
- **Connect all** — syncs every proxy entry at once. The intended way to restore all tunnels after the Home Console restarts.
- **Disconnect all** — closes all tunnels and removes all cloud proxy mappings cleanly.

**Management command** — the same sync operations are available from the command line:

```bash
# Sync all entries
python manage.py sync_tunnels

# Sync one entry by domain name
python manage.py sync_tunnels --domain mysite.example.com

# Disconnect all entries
python manage.py sync_tunnels --disconnect

# Disconnect one entry
python manage.py sync_tunnels --domain mysite.example.com --disconnect
```

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

### 6. Register a base domain

Go to `http://localhost:8001/` (the dashboard) and click **Register base domain**. Enter `mysite.example.com` and submit. This registers the domain with the cloud server; the home is now authorised to create proxy mappings for it and any of its subdomains.

### 7. Add a domain and proxy entry

Go to `http://localhost:8001/domains/add/` and enter `mysite.example.com`. From the domain detail page click **Add** to create a proxy entry — choose scheme `http` and the port certbot will listen on (e.g. `8082`).

### 8. Open the tunnel and obtain a TLS certificate

From the proxy entry detail page click **Open tunnel**, then enter your email and click **Issue certificate**. Wait for certbot to complete — the domain record is updated with the cert path on success.

### 9. Open the tunnel for production traffic

Click **Open tunnel** on the proxy entry (if you closed it after cert issuance), or click **Connect all** on the dashboard to restore all tunnels at once. After any future Home Console restart, **Connect all** is the quickest way to bring everything back up.

### 10. Test

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
