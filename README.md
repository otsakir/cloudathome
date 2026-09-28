## About

CloudAtHome lets you run application servers at home and reach them from the internet through a cloud relay — without opening any inbound firewall port on the home network, and without handing the relay operator anything that would let them read your traffic.

This repo is the **cloud-side** component: HAProxy plus the Django API/SSH server that homes connect to. It's meant to be deployed by whoever is providing the relay — that might be you, running it purely for your own homes, or for a community or family that registers against your instance. This README covers **operating** that cloud server. If you're looking to *connect a home* rather than *operate a cloud server*, you want the other repo instead: the home-side client (the `cah.py` CLI + Home Console Django app that runs *at* a home) lives at **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**.

### Further reading

- [Vision](docs/vision.md) — why the cloud is deliberately kept "dumb", and what that buys a home operator
- [Architecture](docs/architecture.md) — components and the full request/tunnel lifecycle
- [Configuration reference](docs/configuration.md) — every `.env` variable, and which ones can change after install
- [REST API reference](docs/api-reference.md) — the contract home-side clients talk to
- [Home-configurable features](docs/features.md) — base domains, bandwidth throttling, custom inbound ports: home-operator self-service, but useful when triaging a report
- [Testing your deployment locally](docs/local-smoke-test.md) — an end-to-end smoke test on one machine, no real domain needed
- [Roadmap](docs/roadmap.md) — potential future directions


## Deploying the cloud server (docker only)

To deploy and run the cloud server for the first time, follow the four steps below:

### Set up the environment

```bash
cp .env.example .env
```

See [configuration reference](docs/configuration.md) for a detailed reference of all environmental variables supported.

Two difference services are exposed by this system. The cloudathome website/portal + API and the reverse proxy 
entry points that forwards to home services.  

#### Cloudathome website/portal & API

Tweak `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` to set up public ports for the website and API. By default 80/443 ports are used.
Also set `CAH_HOSTNAME` (obligatory) to the hostname you want the portal/api to listen to. This will allow haproxy to properly
demultiplex arriving requests to the portal container instead of the homes services. For TLS support, drop a TLS 
cert/key pair at `docker/django/certs/fullchain.pem` and `docker/django/certs/privkey.pem`. If not found, Django will
use plaintext http. 

#### Reverse proxy entry points

Similarly, tweak `HTTP_INBOUND_DEFAULT_PORT`/`HTTPS_INBOUND_DEFAULT_PORT` to set up the ports that will forward web 
traffic to the homes. Again, 80/443 ports will be used by default.

Important

* Properly setting up the port values above allow running multiple server instances on the same host machine. See
[Running more than one instance on the same host](docs/features.md#running-more-than-one-instance-on-the-same-host) for more on this.
* Using the same ports for the website/portal and the reverse proxy entry points will work just fine.


See [Routing Django's admin/API through HAProxy](docs/features.md#routing-djangos-adminapi-through-haproxy)
for the full picture.

### Configure installation capacity

Next, configure the instance capacity. The number of homes allowed to register and the number
of proxied ports per home (`MAX_HOME_COUNT`, `TUNNEL_PORTS_PER_HOME`, and friends; `.env.example` starts
with a minimal 2 homes × 5 ports). **This is an install-time-only decision — there's no supported way to
change it once homes have registered** — so decide it now if the defaults don't
fit, then lock it in:

```bash
python3 scripts/generate_fleet_config.py
```

This validates those settings, writes the per-home backend definitions into
`docker/haproxy/haproxy.cfg`, derives `TCP_PUBLIC_PORT_RANGE` in `.env` from them,
and writes `fleet_config.json` next to `.env`, which `tunnelagent` mounts
read-only — `docker compose up` fails if this hasn't been run first.

_In case you have already initialized the instance, you will need to reset it by removing `src/var/db.sqlite3` first._

### Build and start the stack

```bash
docker compose -f compose.yaml up --build
```

This starts two containers:
- **haproxy** — listens on ports 80 and 443 (HTTP/HTTPS), the alternate HTTP/HTTPS range from `.env`, and 10000–10099 (TCP forwards)
- **tunnelagent** — Django (reachable only through HAProxy, at `CAH_HOSTNAME` — see below), SSH server on port 8022

HAProxy must pass its health check before `tunnelagent` starts.

On its very first start (empty database), `tunnelagent` runs `migrate` itself. That
also provisions this instance's home slots via the data migration
`core/migrations/0003_provision_homes.py`, sized to the `MAX_HOME_COUNT` in
`fleet_config.json` — fixed for the life of this instance, per the fleet-size note above.
Later restarts don't migrate; after upgrading to a version with new migrations, run
`manage.py migrate` by hand (as below).

The SQLite database is stored outside the container at `src/var/db.sqlite3`.

### Create an admin user (first time only)

```bash
docker compose -f compose.yaml exec tunnelagent python /opt/app/manage.py createsuperuser
```

Restarting an existing instance is just `docker compose -f compose.yaml up`.

Once running (substituting your `CAH_HOSTNAME`):

```commandline
Swagger UI:        http://<CAH_HOSTNAME>/api/schema/swagger/
Django admin:       http://<CAH_HOSTNAME>/admin/login/
```

Want to confirm it all actually works before pointing a real home at it? See [Testing your deployment locally](docs/local-smoke-test.md).


## Administering the server

### Approving a new home operator

Anyone can self-register at `http://<CAH_HOSTNAME>/signup/`, but new accounts are created **inactive** — as the administrator, you're the one who unlocks them:

1. Go to the Django admin at `http://<CAH_HOSTNAME>/admin/`.
2. Open the new user, tick **Active**, and save.

That's the entire admin-side involvement in onboarding. From here the home operator logs into their own dashboard, generates their own API token, and takes it to their own machine to run `cah.py register` — all of that happens on their side, in `cloudathome-client`, not yours.

### The per-home dashboard

Once activated, a home operator's own dashboard (`/home/dashboard/`) shows their home's connection details and a **read-only** list of currently live proxy mappings — creating and removing mappings is a Home Console (home-side) responsibility, not something exposed here. From their dashboard a user can also generate/rotate their own API token, update their registered SSH public key, and release their own home slot.

### Admin-only operations

Two endpoints exist specifically for you as the operator, not for home users (full details in the [API reference](docs/api-reference.md)):

- `GET /api/admin/proxy-mappings/haproxy` — dump every live HAProxy map entry, useful for debugging routing without shelling into the container.
- `POST /api/admin/homes/sync` — re-derive system SSH users from the database on demand (the same reconciliation that already runs automatically on container startup via `reconcile_tunnel_users`/`reconcile_bandwidth`).


## Home-side client

The home-side CLI (`cah.py`) and Home Console (the Django app homes run locally to manage their forwards, certificates, and tunnels) live in a separate repo: **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**. Point your users there for registering a home, managing proxy entries and base domains, obtaining TLS certificates, and managing tunnels.
