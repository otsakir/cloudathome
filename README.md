## About

CloudAtHome lets you run application servers at home and reach them from the internet through a cloud relay — without opening any inbound firewall port on the home network, and without handing the relay operator anything that would let them read your traffic.

This repo is the **cloud-side** component: HAProxy plus the Django API/SSH server that homes connect to. It's meant to be deployed by whoever is providing the relay — that might be you, running it purely for your own homes, or for a community or family that registers against your instance. If you're looking to *connect a home* rather than *operate a cloud server*, you want the other repo instead: the home-side client (the `cah.py` CLI + Home Console Django app that runs *at* a home) lives at **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**.


## Vision

CloudAtHome exists to let people run their own services, on their own hardware, without handing control of the application — or of the data flowing through it — to a third party they don't operate or fully trust. The "cloud" in "cloud proxy" is deliberately just a *relay*: it opens the front door on the public internet, but what's standing behind that door, and the data it serves, stay under the home operator's control. That's not a policy promise; it's enforced by where things are architecturally, and by which side owns the intelligence in the system.

- **The cloud never holds a TLS private key.** The HTTPS frontend in `docker/haproxy/haproxy.cfg` runs in raw TCP passthrough mode: it reads only the hostname (SNI) from the unencrypted TLS ClientHello to pick a backend, then forwards the encrypted bytes on unmodified. Certificates are issued and stored at the home (under `providers/<name>/certbot/` in `cloudathome-client`), so a cloud operator — even a fully compromised one — has nothing that would let them decrypt a home's HTTPS traffic. They can see *which hostname* was requested and *how much* traffic moved; they cannot see what was said.
- **The cloud keeps almost no state of its own.** Proxy mappings live only in HAProxy's runtime maps, never persisted to this repo's database — a cloud restart wipes the record of what's being served until the home re-announces it. There's no durable cloud-side log of a home's service catalog to leak, subpoena, or quietly accumulate.
- **The home never opens an inbound port.** Connectivity is always a reverse SSH tunnel the home initiates outward; the cloud only ever forwards traffic to a port the home explicitly asked for.
- **Anyone can run the cloud side.** This repo isn't meant to funnel everyone through one operator. `cah.py register --cloudserver-url` and the client's per-profile design (one home, several independent cloud connections side by side) exist specifically so a home can connect to a self-hosted community or family instance instead of — or alongside — a shared public one. Standing up your own cloud server with this repo is a first-class use case, not a fallback for people who don't trust the default.

Where this is headed: replacing the SSH-tunnel transport with WireGuard (see `ROADMAP.md`) would remove even the SNI-hostname visibility the cloud has today, leaving it a pure packet forwarder with no application-layer insight at all. Multi-cloud relay support would let a home spread its trust and availability across more than one independent operator, rather than depending on any single cloud instance.


## Architecture

### Components

| Component | Role |
|-----------|------|
| **HAProxy** | HTTPS ingress on port 443 (SNI-based routing) plus a configurable shared range of alternate HTTP/HTTPS ports, and TCP forwarding on ports 10000–10099 (port-based routing). Routes traffic to per-home SSH tunnel ports via runtime-updated map files. |
| **Django + sshd** | REST API and web UI for managing homes and proxy mappings. SSH server that accepts reverse tunnels from home networks. |

### Request & tunnel lifecycle

This is what happens end to end, across both repos, once a cloud server is up and a home has registered against it. None of these steps are things *you*, as the cloud operator, do by hand — they're the home operator's actions and the system's own behavior, described here so the pieces below make sense.

1. A home operator generates an API token from this cloud server's dashboard, then registers using `cloudathome-client` (generating a dedicated SSH key pair by default), which writes the resulting connection details to a local per-profile config file.
2. The home side starts its own Home Console for that profile. A single home client can hold several such profiles side by side — one per cloud server — each run as its own process, started independently.
3. For HTTP/HTTPS forwards, the home first registers one or more **base domains** with the cloud server (e.g. `mysite.example.com`). The cloud enforces that no two homes can claim overlapping domains. The home is then authoritative for that domain and all its subdomains.
4. The home adds forwards from its Home Console — either HTTP/HTTPS (domain-based) or TCP (port-based). Each forward registers a mapping directly in this cloud server's HAProxy (no persistent cloud-side state) and records the allocated tunnel port on the home side. HTTP/HTTPS forwards are only accepted if the hostname falls under one of the home's registered base domains. By default an HTTP/HTTPS forward publishes on the standard port (80/443); the home can instead request a port from this cloud's advertised alternate range (see [Custom HTTP/HTTPS inbound ports](#custom-httphttps-inbound-ports) below) — useful if the home's own network blocks outbound access to the standard ports, or it wants more than one independent entry point.
5. For HTTP/HTTPS forwards: the home opens the SSH tunnel and triggers certificate issuance locally. Certbot runs standalone on the home side; Let's Encrypt validates via the tunnel.
6. The home closes the temporary tunnel if needed, or keeps it open for production traffic.
7. Incoming HTTPS traffic hits this cloud server's HAProxy on port 443, routed by SNI hostname through the tunnel. Incoming TCP traffic hits HAProxy on the allocated public port (10000–10099), routed by destination port through the tunnel.


## Deploying the cloud server

### Running (Docker only)

Docker Compose needs the HTTP/HTTPS inbound port range configured before it will
start — copy the template once per checkout:

```bash
cp .env.example .env
```

The defaults (`8080-8180` for HTTP, `8443-8543` for HTTPS) work out of the box;
edit `.env` if you want a different range. Without a `.env` file, `docker compose up`
fails outright rather than silently skipping the feature.

```bash
docker compose -f compose.yaml up --build
```

This starts two containers:
- **haproxy** — listens on ports 80 and 443 (HTTP/HTTPS), the alternate HTTP/HTTPS range from `.env`, and 10000–10099 (TCP forwards)
- **tunnelagent** — Django API on port 8000, SSH server on port 8022

HAProxy must pass its health check before `tunnelagent` starts.

### First-time setup

```bash
docker compose -f compose.yaml exec tunnelagent python /opt/app/manage.py migrate
docker compose -f compose.yaml exec tunnelagent python /opt/app/manage.py createsuperuser
```

The `migrate` step also provisions the 10 home slots (indices 0–9) automatically via the data migration `tunnels/migrations/0003_provision_homes.py` — this is a fixed capacity for this instance, not something you configure per deployment.

The SQLite database is stored outside the container at `src/var/db.sqlite3`.

Once running:

```commandline
Swagger UI:        http://localhost:8000/api/schema/swagger/
Django admin:       http://localhost:8000/admin/login/
```


## Administering the server

### Approving a new home operator

Anyone can self-register at `http://<cloud-host>:8000/signup/`, but new accounts are created **inactive** — as the administrator, you're the one who unlocks them:

1. Go to the Django admin at `http://<cloud-host>:8000/admin/`.
2. Open the new user, tick **Active**, and save.

That's the entire admin-side involvement in onboarding. From here the home operator logs into their own dashboard, generates their own API token, and takes it to their own machine to run `cah.py register` — all of that happens on their side, in `cloudathome-client`, not yours.

### The per-home dashboard

Once activated, a home operator's own dashboard (`/dashboard/`) shows their home's connection details and a **read-only** list of currently live proxy mappings — creating and removing mappings is a Home Console (home-side) responsibility, not something exposed here. From their dashboard a user can also generate/rotate their own API token, update their registered SSH public key, download a home-side `config.yaml` template (with the auth token and key path left blank, so it's safe to view without leaking a live credential), and release their own home slot.

### Admin-only operations

Two endpoints exist specifically for you as the operator, not for home users (see the full reference below):

- `GET /api/admin/proxy-mappings/haproxy` — dump every live HAProxy map entry, useful for debugging routing without shelling into the container.
- `POST /api/admin/homes/sync` — re-derive system SSH users from the database on demand (the same reconciliation that already runs automatically on container startup via `reconcile_tunnel_users`/`reconcile_bandwidth`).


## REST API reference

This is the contract the home-side client (`cah.py` / Home Console) talks to — useful if you're debugging a home's connection, writing an alternative client, or just want the full picture. It's also browsable interactively when running in debug mode:

- Swagger UI: `http://localhost:8000/api/schema/swagger/`
- ReDoc: `http://localhost:8000/api/schema/redoc/`
- OpenAPI schema: `http://localhost:8000/api/schema/`

#### Home endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/homes/` | List caller's assigned homes |
| POST | `/api/homes/` | Claim a home slot and install SSH key |
| GET | `/api/homes/<slug>/` | Retrieve home details (port ranges, base domains, bandwidth limit) |
| PATCH | `/api/homes/<slug>/` | Rotate SSH public key and/or set/clear bandwidth limit |
| DELETE | `/api/homes/<slug>/` | Release a home slot (also removes its live HAProxy mappings, registered base domains, and bandwidth limit, so none of it carries over to whoever claims the slot next) |
| GET | `/api/homes/<slug>/base-domains/` | List registered base domains |
| POST | `/api/homes/<slug>/base-domains/` | Register a base domain |
| DELETE | `/api/homes/<slug>/base-domains/<domain>/` | Remove a base domain (blocked if active proxy mappings exist under it) |
| GET | `/api/homes/<slug>/proxy-mappings/` | List active HAProxy mappings (HTTP/HTTPS + TCP) for this home |
| POST | `/api/homes/<slug>/proxy-mappings/<scheme>/` | Allocate a tunnel port and register an HTTP/HTTPS mapping (`scheme` = `http`/`https`; hostname must be under a registered base domain; optional `public_port`, defaults to 80/443) |
| DELETE | `/api/homes/<slug>/proxy-mappings/<scheme>/<host>/` | Remove an HTTP/HTTPS forwarding rule from HAProxy |
| POST | `/api/homes/<slug>/proxy-mappings/tcp/` | Allocate a tunnel port and register a raw TCP mapping (public port must be in this home's TCP port range) |
| DELETE | `/api/homes/<slug>/proxy-mappings/tcp/<port>/` | Remove a TCP forwarding rule from HAProxy |
| GET | `/api/config/inbound-ports/<scheme>/` | Get the shared, system-wide inbound port range for HTTP/HTTPS mappings |

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


## What homes configure themselves

These two features are entirely home-operator self-service via the API/Home Console — you don't administer them — but understanding the rules helps when a home operator reports something not working.

### Base domains

Before creating any HTTP/HTTPS proxy entry, a home must register at least one base domain with the cloud server. A base domain is a domain the operator controls in DNS — the cloud enforces that no two homes can claim the same domain or overlapping domains (e.g. if Home A owns `example.com`, Home B cannot register `sub.example.com`), and validates that it's a proper registrable domain (not a bare TLD like `com` or a public suffix like `co.uk`) using the Public Suffix List. Subdomains do not need to be registered separately — once `example.com` is registered, the home can freely create proxy entries for `blog.example.com`, `api.example.com`, etc.

### Bandwidth throttling

A home operator caps their own egress bandwidth via `PATCH /api/homes/<slug>/` (`bandwidth_limit_kbps`, range 100–10,000,000 kbps, `null` = unlimited) — but the enforcement runs on *your* server, so it's worth knowing what it does there. When a limit is set, the cloud server runs, for that home's assigned port range:

```
tc qdisc add dev eth0 root handle 1: htb default 999
tc class add dev eth0 parent 1: classid 1:<N> htb rate <X>kbit ceil <X>kbit
tc filter add dev eth0 parent 1: handle <N> fw classid 1:<N>
iptables -t mangle -A OUTPUT -p tcp --sport <port_low>:<port_high> -j MARK --set-mark <N>
```

All egress TCP traffic sourced from the home's tunnel port range is marked, then shaped through the HTB leaf class at the configured rate; unrelated traffic on your server is unaffected. Since `tc`/`iptables` rules don't survive a container restart, the `reconcile_bandwidth` management command re-applies all limits from the database automatically on container start — you don't need to do this yourself.


### Custom HTTP/HTTPS inbound ports

By default, HTTP/HTTPS proxy mappings publish on the standard port (80/443). This
cloud server can also advertise a **shared, system-wide alternate port range** —
unlike the TCP range, it's not split per home, since HTTP/HTTPS mappings are routed
by hostname (which the cloud already guarantees can't collide across homes), not by
port alone. A home requests a custom port via `public_port` when creating a mapping
(`POST /api/homes/<slug>/proxy-mappings/<scheme>/`), or discovers what's available
via `GET /api/config/inbound-ports/<scheme>/`.

**As the operator, you configure the range once, in `.env`:**

```
HTTP_INBOUND_PORT_RANGE=8080-8180
HTTPS_INBOUND_PORT_RANGE=8443-8543
```

This single value is threaded through `compose.yaml` (published ports on the
`haproxy` container) and `docker/haproxy/haproxy.cfg` (the extra `bind` lines,
via HAProxy's own environment-variable expansion) — you only ever edit it in one
place. **Changing it requires recreating the `haproxy` and `tunnelagent`
containers** (`docker compose up -d --build`), not just a config reload — unlike
map updates (which the Runtime API applies live), the actual set of listening
ports is fixed for the lifetime of the process.

## Home-side client

The home-side CLI (`cah.py`) and Home Console (the Django app homes run locally to manage their forwards, certificates, and tunnels) live in a separate repo: **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**. Point your users there for registering a home, managing proxy entries and base domains, obtaining TLS certificates, and managing tunnels.


## Testing your deployment locally

This is a self-contained smoke test for verifying *your own* cloud stack works, end to end, on one machine — no real domain, DNS, or the home-side client repo needed. You'll be playing both the admin and the home-operator roles yourself here, standing in for a real home with a manual SSH tunnel and raw `curl` calls instead of the Home Console. That's fine for a local check; it's not how a real deployment with a separate home operator works (see the sections above for that).

### 1. Start the cloud stack

```bash
docker compose -f compose.yaml up --build
```

### 2. Sign up and activate an account

Go to `http://localhost:8000/signup/` and register. Log in to the Django admin at `http://localhost:8000/admin/` as the superuser, open the new user, tick **Active**, and save.

### 3. Register a home via the API

There's no web-form "register a home" flow — the dashboard only issues API tokens; registration itself goes through `POST /api/homes/`. Log in at `http://localhost:8000/login/` and click **Generate an API token**, then call the API directly with it:

```bash
TOKEN=<token-from-the-dashboard>

curl -X POST http://localhost:8000/api/homes/ \
    -H "Authorization: Token $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"public_key": "'"$(cat ~/.ssh/id_ed25519.pub)"'"}'
```

Note the **SSH username** (e.g. `home00_alice`), **port base** (e.g. `2000`), and **slug** from the JSON response — the slug identifies this home in every subsequent API call.

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

### 6. Register a base domain and a proxy mapping via the API

Mapping management has no web-form either (it's a Home Console responsibility in normal operation) — register the base domain and create the mapping directly, using the slug from step 3:

```bash
SLUG=<slug-from-step-3>

curl -X POST http://localhost:8000/api/homes/$SLUG/base-domains/ \
    -H "Authorization: Token $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"domain": "mysite.example.com"}'

curl -X POST http://localhost:8000/api/homes/$SLUG/proxy-mappings/https/ \
    -H "Authorization: Token $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"host": "mysite.example.com"}'
```

The second call allocates the lowest free port in the home's range — on a freshly registered home that's the same `2000` used for the tunnel in step 5 — and updates HAProxy's SNI map immediately. Confirm the response's `tunnel_port` matches; if it doesn't (e.g. a previous mapping is still using `2000`), redo step 5 with the returned port instead.

### 7. Test

```bash
curl -k --resolve mysite.example.com:443:127.0.0.1 https://mysite.example.com
```

`--resolve` injects the hostname into the TLS ClientHello without a real DNS entry. `-k` accepts the self-signed certificate. You should see the response from the local service.
