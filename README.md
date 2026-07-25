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
| **`cah.py`** | Home network | Single CLI for the home side: register with a cloud server, start the Home Console for a profile, list registered profiles, and deregister/remove one. Run once (`register`) before starting the Home Console. |

### How it works

1. A home operator generates an API token from the cloud dashboard, then runs `python cah.py register` with that token. It registers the home (generating a dedicated SSH key pair by default), and writes the resulting connection details to a per-profile `home/providers/<name>/config.yaml`.
2. `python cah.py start <name>` starts the Home Console Django app for that profile. A single home client can hold several such profiles side by side — one per cloud server — each run as its own process, started independently.
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
| DELETE | `/api/homes/<slug>/` | Release a home slot (also removes its live HAProxy mappings, registered base domains, and bandwidth limit, so none of it carries over to whoever claims the slot next) |
| GET | `/api/homes/<slug>/base-domains/` | List registered base domains |
| POST | `/api/homes/<slug>/base-domains/` | Register a base domain |
| DELETE | `/api/homes/<slug>/base-domains/<domain>/` | Remove a base domain (blocked if active proxy mappings exist under it) |
| GET | `/api/homes/<slug>/proxy-mappings/` | List active HAProxy mappings for this home |
| POST | `/api/homes/<slug>/proxy-mappings/` | Allocate a tunnel port and register in HAProxy |
| DELETE | `/api/homes/<slug>/proxy-mappings/<key>/` | Remove a forwarding rule from HAProxy |

#### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/authtoken/` | Obtain a token (username/password) |
| DELETE | `/api/auth/token/` | Revoke the caller's own token |

#### Admin-only endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current live HAProxy map entries |
| POST | `/api/admin/homes/sync` | Reconcile DB homes with system SSH users |

---

## Home system

The `home/` directory contains everything needed to connect a home network to one or more cloud servers.

```
home/
├── cah.py                               # single CLI: register / start / list / remove
├── home.yaml.example                    # template for optional global settings (home.yaml)
├── providers/                           # one subdirectory per registered cloud server ("profile")
│   └── <name>/                          # e.g. providers/cloud-example-com/, gitignored
│       ├── config.yaml                  # written by cah.py register — contains secrets
│       ├── db.sqlite3                   # this profile's Home Console database
│       ├── ssh_key / ssh_key.pub        # dedicated key pair for this profile's tunnel
│       └── certbot/                     # created on first certificate issuance
│           ├── config/                  # certbot config and issued certificates
│           ├── work/                    # certbot working directory
│           └── logs/                    # certbot logs
├── providers/config.yaml.example        # template showing all fields for a single profile
├── scripts/
│   └── generate_keys.py                 # standalone: generate an SSH key pair (rarely needed — see below)
└── django/                              # Home Console Django app (one process runs against one active profile)
    ├── cloudlink/                       # config loading, cloud API client, dashboard
    └── domains/                         # domain, certificate, and tunnel management
```

### Prerequisites

- Python 3.11+
- `certbot` CLI installed on the home machine (e.g. `sudo apt install certbot` or `pip install certbot`)
- A registered, active account on the target cloud server (see [User accounts](#user-accounts) above)
- The Home Console's dependencies installed once, up front — `cah.py` itself only needs `requests`/`pyyaml`, but it shells out to `manage.py` (migrations, tunnel sync, running the server), which needs the full Django environment:
  ```bash
  cd home/django
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  ```

### Registering with a new cloud site

Each cloud server you connect to gets its own **profile** under `home/providers/<name>/`, so the same home machine can stay connected to multiple independent cloud servers at once (e.g. a personal cloud and a family member's).

**1. Get an API token from that cloud server's dashboard.** Log in at `http://<cloud-host>:8000/`, and if you don't already have one, click **Generate an API token**. It's shown only once — copy it now.

**2. Run `cah.py register <name>` with that token.** The profile name is a plain positional argument; if you omit it, one is derived from the cloud server's hostname. By default this generates a dedicated SSH key pair for the new profile, registers the home, and writes `home/providers/<name>/config.yaml`:

```bash
cd home
python cah.py register my-cloud \
    --cloudserver-url https://cloud.example.com \
    --token <token-from-the-dashboard>
```

`--cloudserver-url` is optional: omit it to register against the default server (either `default_cloudserver_url` from an optional `home/home.yaml`, copied from `home.yaml.example`, or otherwise the public demo server, `http://cloudathome.retalia.org`) — so registering against the default is just `python cah.py register my-cloud --token <token>`.

On success it prints a summary, runs `manage.py migrate` for the new profile automatically, and tells you how to start it:

```
Done. Configuration written to: providers/my-cloud/config.yaml
  home_slug    : xK3mAbcDef9pQr
  ssh_username : home02_alice
  ssh_host     : cloud.example.com:22
  port range   : 2200 – 2209
  console port : 8001

Start this profile with:
  python cah.py start my-cloud
```

Pass `--public-key`/`--private-key` together instead if you want to bring your own existing key pair rather than generating a dedicated one (`generate_keys.py` is only needed for that path). If automatic migration fails, `cah.py register` tells you to run `manage.py migrate` yourself before starting — registration itself has already succeeded at that point.

### Starting the Home Console

```bash
python cah.py start my-cloud
```

No port or `HOME_CONFIG` bookkeeping needed: `start` auto-assigned and remembered a port for this profile at registration time (or the first time you start it, if it was registered before this existed), reconnects any existing tunnels/mappings automatically (equivalent to the dashboard's "Connect all" — skip with `--no-sync`), then runs the Home Console at `http://localhost:<port>/`. Pass `--port` to override.

### Listing registered profiles

```bash
python cah.py list
```

Purely local and instant (no network calls) — shows each profile's name, cloud server, home slug, console port, and whether it's currently running. Useful once you have more than one profile to keep track of.

### Removing a profile

```bash
python cah.py remove my-cloud
```

Disconnects all tunnels, releases the home slot on the cloud server (which also cleans up this home's live HAProxy mappings, base domains, and bandwidth limit server-side), revokes this profile's API token, and — only once all of that has succeeded — permanently deletes `home/providers/my-cloud/` (database, certificates, SSH key). Prompts for confirmation first; skip it with `--yes`. If any step fails, nothing local is deleted and the error is printed — fix the issue and re-run to retry; it's safe to run more than once.

### Portability

Each profile's state lives entirely under its own `home/providers/<name>/` directory:

| Piece | Default location | Configured by |
|-------|-----------------|---------------|
| Connection config | `home/providers/<name>/config.yaml` | `HOME_CONFIG` env var |
| Database | `home/providers/<name>/db.sqlite3` | `database` in config.yaml |
| TLS certificates | `home/providers/<name>/certbot/` | certbot working directory |
| SSH key pair | `home/providers/<name>/ssh_key` | `ssh.private_key_path` in config.yaml |

To move a profile to another machine: copy its `home/providers/<name>/` directory, update any absolute paths in its `config.yaml`, and run `python cah.py start <name>` as usual.

To run several cloud connections at once, just run `cah.py start` for each profile — each auto-assigned its own port at registration time:

```bash
python cah.py start my-cloud     # e.g. port 8001
python cah.py start family-cloud # e.g. port 8002
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
- **Connect all** — syncs every proxy entry at once. `python cah.py start` already does this automatically on every launch (skip with `--no-sync`); use this button to reconnect without restarting the console.
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

### 3. Generate an API token (cloud dashboard)

Log in at `http://<cloud-host>:8000/`, and click **Generate an API token**. Copy it — it's shown only once.

### 4. Install the Home Console's dependencies (once, home machine)

```bash
cd home/django
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

### 5. Register the home

```bash
python cah.py register \
    --cloudserver-url http://<cloud-host>:8000 \
    --token <token-from-the-dashboard>
```

This generates a dedicated SSH key pair, registers the home, runs `manage.py migrate` for the new profile automatically, and writes `home/providers/<name>/config.yaml` with the assigned SSH username, port range, console port, and auth token (`<name>` defaults to a sanitized form of `<cloud-host>`; pass a name as the first argument to choose your own, e.g. `python cah.py register <name> --token ...`).

### 6. Start the Home Console

```bash
python cah.py start <name>
```

No port or `HOME_CONFIG` bookkeeping needed — it uses the port assigned at registration.

### 7. Register a base domain

Go to `http://localhost:<port>/` (the dashboard) and click **Register base domain**. Enter `mysite.example.com` and submit. This registers the domain with the cloud server; the home is now authorised to create proxy mappings for it and any of its subdomains.

### 8. Add a domain and proxy entry

Go to `http://localhost:<port>/domains/add/` and enter `mysite.example.com`. From the domain detail page click **Add** to create a proxy entry — choose scheme `http` and the port certbot will listen on (e.g. `8082`).

### 9. Open the tunnel and obtain a TLS certificate

From the proxy entry detail page click **Open tunnel**, then enter your email and click **Issue certificate**. Wait for certbot to complete — the domain record is updated with the cert path on success.

### 10. Open the tunnel for production traffic

Click **Open tunnel** on the proxy entry (if you closed it after cert issuance), or click **Connect all** on the dashboard to restore all tunnels at once. After any future restart, `python cah.py start <name>` reconnects everything automatically.

### 11. Test

```bash
curl https://mysite.example.com
```

Traffic hits HAProxy on the cloud server, is routed by SNI through the SSH tunnel, and arrives at your home service.

### 12. (Optional) Remove the home when you're done with it

```bash
python cah.py remove <name>
```

Tears down tunnels, releases the home slot and base domains on the cloud server, revokes the API token, and deletes `home/providers/<name>/`.

---

## Manual testing walkthrough

This walkthrough exercises the cloud stack locally — no real domain or DNS needed. It manually opens an SSH tunnel and adds a proxy mapping via the cloud web UI, without using the Home Console at all.

### 1. Start the cloud stack

```bash
docker compose -f cloud/compose.yaml up --build
```

### 2. Sign up and activate an account

Go to `http://localhost:8000/signup/` and register. Log in to the Django admin at `http://localhost:8000/admin/` as the superuser, open the new user, tick **Active**, and save.

### 3. Register a home via the API

There's no web-form "register a home" flow — the dashboard only issues API tokens; registration itself goes through `POST /api/homes/`. Log in at `http://localhost:8000/login/` and click **Generate an API token**, then call the API directly with it:

```bash
curl -X POST http://localhost:8000/api/homes/ \
    -H "Authorization: Token <token-from-the-dashboard>" \
    -H "Content-Type: application/json" \
    -d '{"public_key": "'"$(cat ~/.ssh/id_ed25519.pub)"'"}'
```

Note the assigned **SSH username** (e.g. `home00_alice`) and **port base** (e.g. `2000`) from the JSON response.

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
