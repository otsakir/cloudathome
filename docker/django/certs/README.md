# TLS cert/key for CAH_HOSTNAME

Drop the cert/key pair gunicorn terminates `CAH_HOSTNAME`'s HTTPS with here (bind-mounted read-only into `tunnelagent` at `/etc/cloudathome/certs/` -- see `compose.yaml` and `docker/django/entrypoint.sh`):

```
fullchain.pem
privkey.pem
```

No ACME/Certbot automation -- obtain these however you like (e.g. Let's Encrypt/Certbot run manually against `CAH_HOSTNAME`, or a self-signed cert for local testing -- see [../../docs/local-smoke-test.md](../../docs/local-smoke-test.md)) and place them here yourself. Both files are gitignored; only this README is tracked, so the directory exists on a fresh checkout.

**`privkey.pem` must be readable by the container's `django` user.** Tools like `openssl req`/`certbot` commonly write it `0600`, owned by whichever user ran them -- since this directory is bind-mounted, that host-side ownership/permissions carry straight into the container, where `django`'s UID almost certainly isn't a match. If it isn't readable, gunicorn's HTTPS process fails silently in the background per-request (`PermissionError` in `docker logs tunnelagent`, connection reset for the client) rather than at container startup. Simplest fix: `chmod 644 docker/django/certs/privkey.pem` after placing it.

**Cert presence is the only toggle.** Both files present -> gunicorn's HTTPS process starts, `CAH_HOSTNAME`'s HTTPS route is wired up in HAProxy, and plain HTTP to `CAH_HOSTNAME` auto-redirects (301) to HTTPS. Either file missing -> HTTP proxies straight through instead, no HTTPS route exists. No separate on/off setting -- see `docker/django/entrypoint.sh` and `HAProxyService.ensure_admin_route`.
