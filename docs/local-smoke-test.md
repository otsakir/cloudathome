# Testing your deployment locally

This is a self-contained smoke test for verifying *your own* cloud stack works, end to end, on one machine — no real domain, DNS, or the home-side client repo needed. You'll be playing both the admin and the home-operator roles yourself here, standing in for a real home with a manual SSH tunnel and raw `curl` calls instead of the Home Console. That's fine for a local check; it's not how a real deployment with a separate home operator works (see the main [README](../README.md) for that).

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
