# REST API reference

This is the contract the home-side client (`cah.py` / Home Console) talks to — useful if you're debugging a home's connection, writing an alternative client, or just want the full picture. It's also browsable interactively when running in debug mode, at `/api/schema/swagger/`, `/api/schema/redoc/`, and `/api/schema/` — in local, non-Docker dev that's `http://localhost:8000/api/schema/swagger/` (`manage.py runserver`); on a deployed instance it's `http://<CAH_HOSTNAME>/api/schema/swagger/`, since Django has no published port of its own (see [Routing Django's admin/API through HAProxy](features.md#routing-djangos-adminapi-through-haproxy)).

### Home endpoints

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

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/authtoken/` | Obtain a token (username/password) |
| DELETE | `/api/auth/token/` | Revoke the caller's own token |

### Admin-only endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/proxy-mappings/haproxy` | Dump current live HAProxy map entries |
| POST | `/api/admin/homes/sync` | Reconcile DB homes with system SSH users |
