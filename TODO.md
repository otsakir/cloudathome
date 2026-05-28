# TODO

## Known Issues

### Security

- **Shell injection surface** (`manage_home.py:206`): `chpasswd` is called with `shell=True`. Username should be validated or the call restructured to avoid shell interpretation.
- **Hardcoded SECRET_KEY** (`backend/settings/local_settings.py:24`): Must be replaced with an environment variable before any non-local deployment.

### Correctness

- **Pubkey filename collision** (`external/services.py`): Pubkey file is named `{username}{home_id}_public_key` with no separator. A username like `alice3` with home 0 produces `alice30_public_key`, colliding with username `alice` and home 30. Fix: use `{username}_{home_id}_public_key`.
- **No transaction management** (`external/services.py`): If the `manage_home.py` subprocess fails after the pubkey file has been written, the file is left behind.
- **`PermitListen` interface** (`manage_home.py`): Uncommitted change switches `LISTENING_NETWORK_INTERFACE` from `0.0.0.0` to `*` — the correct OpenSSH wildcard for all interfaces. Needs to be committed.
- **Race condition in home claiming** (`api/views.py:70-71`): Two concurrent POST requests to `/api/homes/` can both see the same available slot and claim it. Fix: wrap the find-and-assign in `select_for_update()` inside `transaction.atomic()`.
- **`OutHomeSerializer` missing `home_index`** (`api/serializers.py:62-63`): Response after claiming a home omits the `home_index`, so the client cannot construct the DELETE URL `/api/homes/<id>/`.
- **`HomeSerializer.update` uses bare `assert`** (`api/serializers.py:34`): Silently skipped when Python runs with `-O`. Replace with an explicit guard that raises a proper exception.

### Robustness

- **Bare `except Exception`** (`api/views.py:36,74,102,122,144,157,178`): All error handlers silently swallow exceptions with no logging. At minimum, log the exception before returning an error response.
- **No logging**: Critical operations (user creation, proxy mapping changes, sshd reload) produce no audit trail anywhere in the Django layer.
- **No validation that AllowUsers directive exists** (`manage_home.py`): `add_username_to_allow_users` and `remove_username_from_allow_users` assume the directive is already present in the sshd config file. The script could fail silently or corrupt the config on a fresh environment.

### Code Quality

- **Unused imports** (`api/views.py`, `api/serializers.py`): `sys` imported but never used in both files; `HttpRequest` unused in views.py.
- **`HomeSerializer` and `CreateHomeSerializer` are identical** (`api/serializers.py`): Both serialize only `public_key`. One is redundant and should be removed.
- **`HomeSyncView` duplicates `reconcile_tunnel_users` management command** (`api/views.py:164`, `api/management/commands/reconcile_tunnel_users.py`): Same logic maintained in two places.
- **No tests for API views** (`api/tests.py`): File contains only a trivial placeholder. Views, serializers, and permission logic have no coverage.

### Incomplete / Stub Code

- **`ProxyInstanceAPIView`** (`api/views.py:132`): Defined as a bare `pass`, but wired to `/api/proxy/instance/` in `urls.py`. Either implement or remove.
