## About

A system that allows running application servers at home and making them reachable from the internet via a cloud proxy — without opening any inbound firewall ports on the home network.

This repo is the **cloud-side** component: HAProxy plus the Django API/SSH server that homes connect to. The home-side client (the CLI + Home Console that runs *at* a home) lives in a separate repo: **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**.


## Overview

### Sites

* A **cloud server** (this repo) running on any typical cloud provider. It is the entry point for all HTTPS traffic.
* A **home network** — one or more hosts behind NAT that run the services you want to expose, using [cloudathome-client](https://github.com/otsakir/cloudathome-client).

### Components

| Component | Role |
|-----------|------|
| **HAProxy** | HTTPS ingress on port 443 (SNI-based routing) and TCP forwarding on ports 10000–10099 (port-based routing). Routes traffic to per-home SSH tunnel ports via runtime-updated map files. |
| **Django + sshd** | REST API and web UI for managing homes and proxy mappings. SSH server that accepts reverse tunnels from home networks. |

The home-side counterparts (`cah.py` CLI, Home Console Django app) are documented in [cloudathome-client](https://github.com/otsakir/cloudathome-client)'s own README/CLAUDE.md.

### How it works

1. A home operator generates an API token from this cloud server's dashboard, then registers using `cloudathome-client` (generating a dedicated SSH key pair by default), which writes the resulting connection details to a local per-profile config file.
2. The home side starts its own Home Console for that profile. A single home client can hold several such profiles side by side — one per cloud server — each run as its own process, started independently.
3. For HTTP/HTTPS forwards, the operator first registers one or more **base domains** with the cloud server (e.g. `mysite.example.com`). The cloud enforces that no two homes can claim overlapping domains. The home is then authoritative for that domain and all its subdomains.
4. The operator adds forwards from the Home Console — either HTTP/HTTPS (domain-based) or TCP (port-based). Each forward registers a mapping directly in HAProxy on this cloud server (no persistent cloud-side state) and records the allocated tunnel port on the home side. HTTP/HTTPS forwards are only accepted if the hostname falls under one of the home's registered base domains.
5. For HTTP/HTTPS forwards: the operator opens the SSH tunnel and triggers certificate issuance from the home side. Certbot runs standalone there; Let's Encrypt validates via the tunnel.
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

### Base domains

Before creating any HTTP/HTTPS proxy entry, a home must register at least one base domain with the cloud server. A base domain is a domain the operator controls in DNS — the cloud enforces that no two homes can claim the same domain or overlapping domains (e.g. if Home A owns `example.com`, Home B cannot register `sub.example.com`), and validates that it's a proper registrable domain (not a bare TLD like `com` or a public suffix like `co.uk`) using the Public Suffix List. Subdomains do not need to be registered separately — once `example.com` is registered, the home can freely create proxy entries for `blog.example.com`, `api.example.com`, etc. See the REST API table above for the `base-domains` endpoints; the home-side UX for registering/removing them lives in `cloudathome-client`.

### Bandwidth throttling

Per-home bandwidth limits cap how much of the home's internet upload the cloud tunnel can consume, set/cleared via `PATCH /api/homes/<slug>/` (`bandwidth_limit_kbps`, range 100–10,000,000 kbps, `null` = unlimited). Enforced using Linux `tc` (HTB) and `iptables`; TCP backpressure through the SSH connection naturally bounds the home-side upload rate.

When a limit is set, the cloud server runs, for the home's assigned port range:

```
tc qdisc add dev eth0 root handle 1: htb default 999
tc class add dev eth0 parent 1: classid 1:<N> htb rate <X>kbit ceil <X>kbit
tc filter add dev eth0 parent 1: handle <N> fw classid 1:<N>
iptables -t mangle -A OUTPUT -p tcp --sport <port_low>:<port_high> -j MARK --set-mark <N>
```

All egress TCP traffic sourced from the home's tunnel port range is marked, then shaped through the HTB leaf class at the configured rate. Unrelated traffic is unaffected. Since `tc`/`iptables` rules don't survive a container restart, the `reconcile_bandwidth` management command re-applies all limits from the database on container start.

---

## Home-side client

The home-side CLI (`cah.py`) and Home Console (the Django app homes run locally to manage their forwards, certificates, and tunnels) live in a separate repo: **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**. See that repo for registering a home, managing proxy entries and base domains from the home side, obtaining TLS certificates, and managing tunnels.

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

### 4. Register and start the home side

The rest of this walkthrough (installing the client, registering the home, starting the
Home Console, registering a base domain, adding a proxy entry, obtaining a TLS
certificate, and testing) happens in **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**
— see its README for the full sequence, using the API token from step 3 above.

Once done, incoming HTTPS traffic hits HAProxy on this cloud server, is routed by SNI
through the SSH tunnel, and arrives at the home service.

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
