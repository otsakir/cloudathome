# Testing your deployment locally

This is a self-contained smoke test for verifying *your own* cloud stack works, end to end, on one machine — no real domain or the home-side client repo needed. You'll be playing both the admin and the home-operator roles yourself here, standing in for a real home with a manual SSH tunnel and raw `curl` calls instead of the Home Console. That's fine for a local check; it's not how a real deployment with a separate home operator works (see the main [README](../README.md) for that).

Unlike a real deployment, there's no real DNS here either — for both `CAH_HOSTNAME` (Django's own admin/API) and the home's mapping hostname later on, we'll fake hostname resolution locally instead.

### 1. Set `CAH_HOSTNAME` and generate a local cert

`CAH_HOSTNAME` is required — Django is only reachable through it, there's no separate port. Pick a hostname that isn't a real domain you own, e.g. `admin.local.test`, and set it in `.env`:

```bash
cp .env.example .env
# then edit .env: CAH_HOSTNAME=admin.local.test
```

Add a hosts-file entry so your browser/`curl` resolve it to this machine:

```bash
echo "127.0.0.1 admin.local.test" | sudo tee -a /etc/hosts
```

Generate a self-signed cert/key for gunicorn to terminate `CAH_HOSTNAME`'s HTTPS with (no ACME automation — see [Home-configurable features](features.md#routing-djangos-adminapi-through-haproxy)):

```bash
mkdir -p docker/django/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout docker/django/certs/privkey.pem \
    -out docker/django/certs/fullchain.pem \
    -subj "/CN=admin.local.test"
chmod 644 docker/django/certs/privkey.pem
```

The `chmod` matters: `openssl req` writes the key `0600`, owned by you; since this directory is bind-mounted, that ownership carries straight into the container, where it won't be readable by the `django` user gunicorn runs as (see [docker/django/certs/README.md](../docker/django/certs/README.md)).

### 2. Start the cloud stack

```bash
python3 scripts/generate_fleet_config.py
docker compose -f compose.yaml up --build
```

If `CAH_HOSTNAME` isn't set, `tunnelagent` fails to start outright (`reconcile_admin_route` refuses to leave Django unreachable) — that's expected if you skipped step 1.

### 3. Sign up and activate an account

Go to `https://admin.local.test/signup/` and register — your browser will warn about the self-signed cert, since it's not from a real CA; accept it. Log in to the Django admin at `https://admin.local.test/admin/` as the superuser, open the new user, tick **Active**, and save.

`http://admin.local.test/signup/` (no `s`) also gets you there — HAProxy 301-redirects it to HTTPS automatically, since a cert is present (see [Home-configurable features](features.md#routing-djangos-adminapi-through-haproxy)).

### 4. Register a home via the API

There's no web-form "register a home" flow — the dashboard only issues API tokens; registration itself goes through `POST /api/homes/`. Log in at `https://admin.local.test/login/` and click **Generate an API token**, then call the API directly with it:

```bash
TOKEN=<token-from-the-dashboard>

curl -k -X POST https://admin.local.test/api/homes/ \
    -H "Authorization: Token $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"public_key": "'"$(cat ~/.ssh/id_ed25519.pub)"'"}'
```

(`-k` accepts the same self-signed cert as the browser did.) Note the **SSH username** (e.g. `home00_alice`), **port base** (e.g. `2000`), and **slug** from the JSON response — the slug identifies this home in every subsequent API call.

### 5. Start a local service to expose

```bash
docker run --rm -p 8443:80 nginx
```

This starts nginx on `localhost:8443`.

### 6. Open the reverse SSH tunnel manually

```bash
ssh -N -T -R 127.0.0.1:2000:localhost:8443 home00_alice@localhost -p 8022
```

This forwards **port 2000 on the cloud server** → **port 8443 on this machine**. The command hangs — that is correct; it holds the tunnel open.

### 7. Register a base domain and a proxy mapping via the API

Mapping management has no web-form either (it's a Home Console responsibility in normal operation) — register the base domain and create the mapping directly, using the slug from step 4. This home's own hostname (`mysite.example.com`) is unrelated to `CAH_HOSTNAME` — it doesn't need a hosts-file entry until the test step below:

```bash
SLUG=<slug-from-step-4>

curl -k -X POST https://admin.local.test/api/homes/$SLUG/base-domains/ \
    -H "Authorization: Token $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"domain": "mysite.example.com"}'

curl -k -X POST https://admin.local.test/api/homes/$SLUG/proxy-mappings/https/ \
    -H "Authorization: Token $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"host": "mysite.example.com"}'
```

The second call allocates the lowest free port in the home's range — on a freshly registered home that's the same `2000` used for the tunnel in step 6 — and updates HAProxy's SNI map immediately. Confirm the response's `tunnel_port` matches; if it doesn't (e.g. a previous mapping is still using `2000`), redo step 6 with the returned port instead.

### 8. Test

```bash
curl -k --resolve mysite.example.com:443:127.0.0.1 https://mysite.example.com
```

`--resolve` injects the hostname into the TLS ClientHello without a real DNS entry (an alternative to the `/etc/hosts` edit used for `CAH_HOSTNAME` above — either works, this just avoids needing `sudo` for a domain you'll only use once). `-k` accepts the home's own self-signed certificate. You should see the response from the local service.
