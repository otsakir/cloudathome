# Configuration reference

An instance is configured through the root `.env` file (`cp .env.example .env`),
plus `fleet.env` (`cp fleet.env.example fleet.env`) for the install-time-only
fleet size, which only `./setup` reads.
`docker compose` substitutes these variables into `compose.yaml`, which in turn
passes them to the containers; HAProxy expands them in `haproxy.cfg`'s `bind`
lines, and Django reads them in `config/settings/local_settings.py`.

Variables fall into three groups:

| Group | Meaning |
|---|---|
| [Changeable](#changeable-after-install) | May be edited after install; takes effect on container recreate |
| [Install-time only](#install-time-only-fleet-size) | In `fleet.env`. Fixed for the life of the instance; changing them means `./setup --reset` |
| [Calculated](#calculated) | Written into `.env` by `./setup`; don't edit by hand |

## Applying changes

Every variable is read once, at container start. HAProxy's seamless `SIGUSR2`
reload does **not** pick up changes, so the containers must be recreated.

- **Always recreate both containers together.** Plain `docker compose up -d`
  does this, since both containers' environment changed. Most variables are
  read by both `haproxy` and `tunnelagent`, and nothing checks that they agree:
  recreating only one (e.g. `docker compose up -d tunnelagent`) leaves Django
  validating new mappings against the new ports while HAProxy still listens on
  the old ones — a mapping on a new port is accepted but never gets traffic.
- **Recreating `haproxy` clears its routing maps.** Homes must re-register
  their mappings afterwards (the home-side client does this on reconnect).
  `CAH_HOSTNAME`'s own route is re-seeded automatically when `tunnelagent`
  starts.

## Changeable after install

### This instance's own endpoint

#### `CAH_HOSTNAME` (required)

Hostname this instance's own Django (admin/API/web UI) answers on. Django has no
published port of its own — it's reachable only through HAProxy, routed by this
hostname. Served over HTTP, and also over HTTPS once a cert/key pair is placed in
`docker/django/certs/` (see [features](features.md#routing-djangos-adminapi-through-haproxy)).
`tunnelagent` refuses to start if it's unset.

It's reserved: no home can register it, or a domain overlapping it, as a base
domain.

*On change:* the cert must match the new name. Base domains already registered
are not re-checked against the new reserved name. If only `tunnelagent` is
recreated, the old hostname's map entries stay live until `haproxy` restarts.

#### `CAH_HTTP_PORT` / `CAH_HTTPS_PORT` (default 80 / 443)

The standard HTTP/HTTPS ports this instance's HAProxy listens on, and the ports
`CAH_HOSTNAME` is served on. Overridable so more than one CloudAtHome instance
can share a host — only one process can bind the real `0.0.0.0:80`/`:443`
(see [features](features.md#running-more-than-one-instance-on-the-same-host)).

They may overlap any of the inbound ports below: HAProxy enables `SO_REUSEPORT`
on its listeners, so `bind` lines on the same port coexist.

*On change:* home mappings are unaffected (they use `*_INBOUND_DEFAULT_PORT`);
only the admin/API URL changes.

#### `CAH_SSH_PORT` (default 8022)

Host port that homes connect their SSH reverse tunnel to — the host side of
`tunnelagent`'s port 22. Advertised to homes via the API (`ssh_port`).

*On change:* homes that are already configured keep using the old port until
their client config is updated.

#### `HAPROXY_API_PORT` (default 9999)

HAProxy Runtime API port. Django uses it to update the routing maps, and the
`haproxy` healthcheck probes it. Internal to the compose network, never
published — safe to change.

### Homes' public HTTP/HTTPS ports

#### `HTTP_INBOUND_DEFAULT_PORT` / `HTTPS_INBOUND_DEFAULT_PORT` (default 80 / 443)

The `public_port` a home's HTTP/HTTPS mapping gets when the home doesn't request
one. Deliberately independent of `CAH_HTTP_PORT`/`CAH_HTTPS_PORT`: an operator
moving those for multi-instance reasons can keep homes defaulting to 80/443.
Each gets its own `bind` line in `haproxy.cfg`.

Must be set: `compose.yaml` uses it directly in `ports:`, so a blank value
breaks startup (even though Django alone would fall back to `CAH_HTTP_PORT`).

*On change:* only mappings created afterwards are affected. Homes that
re-register without an explicit `public_port` move to the new port, changing
their public URLs.

#### `HTTP_INBOUND_PORT_RANGE` / `HTTPS_INBOUND_PORT_RANGE` (`.env.example`: `8080-8084` / `8443-8447`)

A shared range of extra public ports for HTTP/HTTPS mappings, in `base-max`
form (inclusive). Unlike raw TCP ports, the range is **not** split per home:
any home may use any port in it, because HTTP/HTTPS traffic is routed by
hostname (plus port), and hostnames can't collide across homes. Homes discover
the range via `GET /api/config/inbound-ports/<scheme>/` and request a port with
`public_port` when creating a mapping.

The range is used in two places:

1. HAProxy binds it (`bind "*:$HTTP_INBOUND_PORT_RANGE"`) and `compose.yaml`
   publishes it.
2. Django checks a requested `public_port` against it — **only when a mapping
   is created**. Existing mappings are never re-checked.

*On change:*

- **Widening** the range, or moving it while keeping every port in use inside
  it, is safe.
- **Shrinking** it breaks mappings on ports that fall outside. Recreating
  `haproxy` clears all mappings anyway; when a home re-registers one on a
  dropped port, the API answers `400` with `code: public_port_not_offered` and
  the ports currently offered. The home-side client shows this reason on the
  entry; the home operator must re-create it on an offered port.
- Mappings on the default port are never affected.

### Dev/testing

#### `BASE_DOMAIN_ALLOW_NON_REGISTRABLE` (default false)

Lets a home register a base domain that isn't a real registrable domain
(normally checked against the Public Suffix List) — e.g. `localhost`,
`myapp.local`. Only that check is relaxed; the `CAH_HOSTNAME` reservation and
cross-home overlap checks still apply. Leave it off on a real deployment.

*On change:* affects new registrations only; domains already registered stay.

## Install-time only (fleet size)

These size the fleet: how many homes the instance holds and how ports are laid
out per home. They live in `fleet.env` and are read **only** by `./setup`, never
by the containers (`./setup` errors if one is still in `.env`). The script:

1. validates them,
2. generates the per-port tunnel backends in `docker/haproxy/haproxy.cfg`,
3. derives `TCP_PUBLIC_PORT_RANGE` and writes it back into `.env`,
4. writes `fleet_config.json` next to `.env`, which `tunnelagent` mounts
   read-only. `manage_home.py` (which runs as root) trusts only this file,
   never the environment.

Run it before the first `docker compose up` — `up` fails without
`fleet_config.json`. The first start then migrates the empty database, creating
`MAX_HOME_COUNT` home slots; after that the script refuses to run again, and
editing `fleet.env` has no effect.

`fleet.env.example` ships a deliberately minimal fleet (2 homes, 5 ports each) —
size it for your deployment before running the script. A variable left out of
`fleet.env` falls back to the built-in default in `manage_home.py`'s `FLEET_DEFAULTS`
(shown in the tables below), which is also what local dev and the test suites
use.

There is no supported way to change these once homes are registered: shrinking
silently breaks routing for homes above the new bound, and growing is untested
against an existing database. A real change means starting over: `docker compose
down`, then `./setup --reset`, which backs up and removes the database (all homes,
users and tokens) before regenerating.

#### `MAX_HOME_COUNT` (`fleet.env.example`: 2, built-in default: 10)

How many home slots the instance holds (indices `0..MAX_HOME_COUNT-1`).

### Internal SSH tunnel ports

Ports inside the `tunnelagent` container where each home's SSH reverse tunnel
listens (restricted per home via sshd's `PermitListen`), and that HAProxy's
tunnel backends forward to. They're also what the bandwidth limiter matches on.
Never published on the host — they only need to avoid `tunnelagent`'s own
listeners (22, 8000, 8001). Homes learn their block from the API (`port_base`,
`port_count`).

| Variable | `fleet.env.example` | Built-in default | Meaning |
|---|---|---|---|
| `TUNNEL_PORTS_BASE` | 2000 | 2000 | Home 0's first tunnel port |
| `TUNNEL_PORTS_PER_HOME` | 5 | 10 | Tunnel ports per home — one per active mapping, so also the max mappings per home |
| `TUNNEL_PORTS_PER_HOME_RESERVED` | 10 | 100 | Stride between homes' blocks: home *i* starts at `TUNNEL_PORTS_BASE + i × TUNNEL_PORTS_PER_HOME_RESERVED`. Must be ≥ `TUNNEL_PORTS_PER_HOME`; the excess is unused headroom |

### Public raw TCP ports

Published on the host. Each home gets a dedicated block for raw TCP forwards
(routed by port alone, hence per-home rather than shared). Homes learn their
block from the API (`tcp_port_base`, `tcp_port_count`).

| Variable | `fleet.env.example` | Built-in default | Meaning |
|---|---|---|---|
| `TCP_PUBLIC_PORTS_BASE` | 10000 | 10000 | Home 0's first public TCP port |
| `TCP_PUBLIC_PORTS_PER_HOME` | 5 | 10 | Public TCP ports per home |

## Calculated

#### `TCP_PUBLIC_PORT_RANGE`

The full public TCP range, in `base-max` form:
`TCP_PUBLIC_PORTS_BASE` to `TCP_PUBLIC_PORTS_BASE + MAX_HOME_COUNT × TCP_PUBLIC_PORTS_PER_HOME − 1`.
Written into `.env` by `./setup`; HAProxy binds it and
`compose.yaml` publishes it. Don't edit it by hand — change the variables it's
derived from (at install time) and rerun the script.
