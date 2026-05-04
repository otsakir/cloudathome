# TODO

## Known Issues

### Security

- **Shell injection surface** (`manage_tunnel.py:206`): `chpasswd` is called with `shell=True`. Username should be validated or the call restructured to avoid shell interpretation.
- **Hardcoded SECRET_KEY** (`backend/settings/local_settings.py:24`): Must be replaced with an environment variable before any non-local deployment.

### Correctness

- **Pubkey filename collision** (`external/services.py`): Pubkey file is named `{username}{home_id}_public_key` with no separator. A username like `alice3` with home 0 produces `alice30_public_key`, colliding with username `alice` and home 30. Fix: use `{username}_{home_id}_public_key`.
- **No transaction management** (`external/services.py`): If the `manage_tunnel.py` subprocess fails after the pubkey file has been written, the file is left behind.
- **`PermitListen` interface** (`manage_tunnel.py`): Uncommitted change switches `LISTENING_NETWORK_INTERFACE` from `0.0.0.0` to `*` — the correct OpenSSH wildcard for all interfaces. Needs to be committed.

### Robustness

- **Bare `except Exception`** (`api/views.py:36,74,102,122,144,157,178`): All error handlers silently swallow exceptions with no logging. At minimum, log the exception before returning an error response.
- **No logging**: Critical operations (user creation, proxy mapping changes, sshd reload) produce no audit trail anywhere in the Django layer.
- **No validation that AllowUsers directive exists** (`manage_tunnel.py`): `add_username_to_allow_users` and `remove_username_from_allow_users` assume the directive is already present in the sshd config file. The script could fail silently or corrupt the config on a fresh environment.

### Incomplete / Stub Code

- **`ProxyInstanceAPIView`** (`api/views.py:132`): Defined as a bare `pass`, but wired to `/api/proxy/instance/` in `urls.py`. Either implement or remove.
