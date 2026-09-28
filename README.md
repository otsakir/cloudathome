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

Two different services are exposed by this system. The cloudathome website/portal + API and the reverse proxy 
entry points that forward to home services.  

#### Cloudathome website/portal & API

Tweak `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` to set up public ports for the website and API. By default 80/443 ports are used.
Also set `CAH_HOSTNAME` (obligatory) to the hostname you want the portal/api to listen to. This will allow haproxy to properly
demultiplex arriving requests to the portal container instead of the homes services. For TLS support, drop a TLS 
cert/key pair at `docker/django/certs/fullchain.pem` and `docker/django/certs/privkey.pem`, and `chmod 644` the key
so the container's `django` user can read it (see [docker/django/certs/README.md](docker/django/certs/README.md),
including a self-signed option for local testing). If not found, Django will use plaintext http. 

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

The capacity of the service regarding maximum number of homes and ports supported is controlled through `fleet.env`,
a separate .env file. Copy fleet.env.example over to fleet.env and tweak`MAX_HOME_COUNT`, `TUNNEL_PORTS_PER_HOME`. 
Note, **this is an setup-time-only decision — there's no supported way to change it once homes have registered** without
clearing the database.

Make up your mind, then lock it in:

```bash
cp fleet.env.example fleet.env
./setup
```

#### Reset capacity configuration
Once the instance has started, `./setup` refuses to run again. To start over, run `docker compose down`
and then `./setup --reset`: this wipes all homes, users and tokens (the database is backed up to
`src/var/db.sqlite3.bak-<timestamp>` first).

### Build and start the stack

```bash
docker compose -f compose.yaml up --build
```

This starts two containers:
- **haproxy**, that listens on `CAH_HTTP_PORT`/`CAH_HTTPS_PORT` (80/443 by default) and `HTTP_INBOUND_DEFAULT_PORT`/`HTTPS_INBOUND_DEFAULT_PORT`
  for web traffic and `TCP_PUBLIC_PORT_RANGE` for raw TCP forwards.
- **tunnelagent**, the Django container and SSH server on `CAH_SSH_PORT` (8022 by default). Only traffic that targets
  `CAH_HOSTNAME` will be forwarded to it.

HAProxy must pass its health check before `tunnelagent` starts.

#### Migrations

Django migrations are run by default when `up`ing for the first time docker containers. Applying further 
migrations need an explicit step:

```bash
docker compose -f compose.yaml exec -u django tunnelagent python /opt/app/manage.py migrate
```

The SQLite database is stored outside the container at `src/var/db.sqlite3`.

### Create an admin user 

Having started the system, create the superuser as normally done in a django installation. 

```bash
docker compose -f compose.yaml exec -u django tunnelagent python /opt/app/manage.py createsuperuser
```

### Accessing the website and API

Once running, access the website/ports, django administrator or the RESTfull API :

```commandline
Website/portal:     http(s)://<CAH_HOSTNAME[:CAH_HTTP(S)_PORT]>
Django admin:       http(s)://<CAH_HOSTNAME[:CAH_HTTP(S)_PORT]>/admin/login/
Swagger UI:         http(s)://<CAH_HOSTNAME[:CAH_HTTP(S)_PORT>/api/schema/swagger/
```

Swagger is only served while django `DEBUG` setting is on, which the Docker settings currently inherit from local dev.


## Administering the server

### Approving a new home operator

Anyone can self-register at `http(s)://<CAH_HOSTNAME>/signup/`. New accounts are created **inactive**. As 
the administrator, you're the one who unlocks them:

1. Go to the Django admin at `http(s)://<CAH_HOSTNAME>/admin/`.
2. Open the new user, tick **Active**, and save.

That's the entire admin-side involvement in onboarding. From here the home operator logs into their own dashboard, 
generates their own API token, and registers their home to the server. See **[otsakir/cloudathome-client](https://github.com/otsakir/cloudathome-client)**
on how this works and completes the picture.

