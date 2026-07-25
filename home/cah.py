#!/usr/bin/env python3
"""
Manage this home's connection(s) to CloudAtHome cloud server(s).

Usage:
    python cah.py register [myhome] --token <api-token-from-the-dashboard> [--cloudserver-url URL]
    python cah.py start myhome [--port PORT] [--no-sync]
    python cah.py list
    python cah.py remove myhome [--yes]

Each registration gets its own profile directory under home/providers/<name>/, so the
same client can stay connected to several cloud servers side by side (one `runserver`
process per profile, each with its own port). `--cloudserver-url` is optional: if
omitted, it falls back to `default_cloudserver_url` in home/home.yaml, or otherwise to
a hardcoded default (the public demo server) -- so registering against the default
server is just `python cah.py register --token <token>`.
"""
import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print('Error: requests is not installed. Run: pip install requests', file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    print('Error: pyyaml is not installed. Run: pip install pyyaml', file=sys.stderr)
    sys.exit(1)

_HOME_DIR = Path(__file__).resolve().parent
_MANAGE_PY = _HOME_DIR / 'django' / 'manage.py'

DEFAULT_CLOUDSERVER_URL = 'http://cloudathome.retalia.org'
DEFAULT_HOME_CONSOLE_PORT_BASE = 8001


def _error(msg):
    print(f'Error: {msg}', file=sys.stderr)
    sys.exit(1)


def _load_yaml(path):
    try:
        return yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _load_home_yaml():
    return _load_yaml(_HOME_DIR / 'home.yaml')


def _resolve_default_cloudserver_url():
    return _load_home_yaml().get('default_cloudserver_url') or DEFAULT_CLOUDSERVER_URL


def _validate_profile_name(name):
    """Guard against unsafe directory names: must be a single, visible path component."""
    if not name or '/' in name or os.sep in name or name.startswith('.'):
        _error(f"invalid profile name '{name}': must be a plain name, no '/' and no leading dot")


def _sanitize_for_dirname(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or 'home'


def _suggest_profile_name(providers_dir, ssh_host):
    """Default profile directory name: sanitized ssh host, disambiguated with a numeric suffix."""
    base = _sanitize_for_dirname(ssh_host)
    if not (providers_dir / base).exists():
        return base
    n = 2
    while (providers_dir / f'{base}-{n}').exists():
        n += 1
    return f'{base}-{n}'


def _profile_config_path(name):
    config_path = _HOME_DIR / 'providers' / name / 'config.yaml'
    if not config_path.exists():
        _error(f"no such profile: {name} (run 'python cah.py register {name} ...' first, "
               f"or 'python cah.py list' to see what's registered)")
    return config_path


def _pick_free_port(providers_dir):
    base = _load_home_yaml().get('home_console_port_base', DEFAULT_HOME_CONSOLE_PORT_BASE)
    used = set()
    if providers_dir.exists():
        for cfg_path in providers_dir.glob('*/config.yaml'):
            port = _load_yaml(cfg_path).get('home_console_port')
            if port:
                used.add(port)
    port = base
    while port in used:
        port += 1
    return port


def _is_port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=0.3):
            return True
    except OSError:
        return False


def _run_manage(config_path, *cmd_args, capture=True):
    env = dict(os.environ, HOME_CONFIG=str(config_path))
    return subprocess.run(
        [sys.executable, str(_MANAGE_PY), *cmd_args],
        env=env,
        capture_output=capture,
        text=True,
    )


def _generate_keypair(private_key_path):
    """Generate a fresh ed25519 keypair at private_key_path. Returns the public key content."""
    result = subprocess.run(
        ['ssh-keygen', '-t', 'ed25519', '-f', str(private_key_path), '-N', ''],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _error(f'ssh-keygen failed:\n{result.stderr}')
    private_key_path.chmod(0o600)
    return private_key_path.with_suffix('.pub').read_text().strip()


def cmd_register(args):
    if bool(args.public_key) != bool(args.private_key):
        _error('--public-key and --private-key must be given together')

    cloudserver_url = args.cloudserver_url or _resolve_default_cloudserver_url()
    base_url = cloudserver_url.rstrip('/')
    ssh_host = urlparse(base_url).hostname
    providers_dir = _HOME_DIR / 'providers'

    if args.output:
        output_path = args.output
        profile_dir = output_path.parent
    else:
        if args.name:
            _validate_profile_name(args.name)
            profile_dir = providers_dir / args.name
            if profile_dir.exists():
                _error(f'profile already exists: {profile_dir}')
        else:
            profile_dir = providers_dir / _suggest_profile_name(providers_dir, ssh_host)
        output_path = profile_dir / 'config.yaml'

    with tempfile.TemporaryDirectory() as tmpdir:
        if args.public_key:
            try:
                public_key_content = args.public_key.read_text().strip()
            except FileNotFoundError:
                _error(f'public key file not found: {args.public_key}')
            if not args.private_key.exists():
                _error(f'private key file not found: {args.private_key}')
            private_key_path = args.private_key.resolve()
        else:
            print('Generating a dedicated SSH keypair for this profile...')
            tmp_private_key = Path(tmpdir) / 'ssh_key'
            public_key_content = _generate_keypair(tmp_private_key)
            private_key_path = None  # finalized below, once profile_dir exists

        print('Registering home...')
        try:
            resp = requests.post(
                f'{base_url}/api/homes/',
                json={'public_key': public_key_content},
                headers={'Authorization': f'Token {args.token}'},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            _error(f'home registration failed: {e}')

        home = resp.json()

        profile_dir.mkdir(parents=True, exist_ok=True)

        if private_key_path is None:
            private_key_path = profile_dir / 'ssh_key'
            shutil.move(str(tmp_private_key), str(private_key_path))
            shutil.move(str(tmp_private_key) + '.pub', str(private_key_path) + '.pub')
            private_key_path = private_key_path.resolve()

        home_console_port = _pick_free_port(providers_dir)

        config = {
            'cloudlink': {
                'cloudserver_url': base_url,
                'auth_token': args.token,
                'home_slug': home['slug'],
                'ssh': {
                    'host': ssh_host,
                    'port': home['ssh_port'],
                    'username': home['ssh_username'],
                    'private_key_path': str(private_key_path),
                },
                'ports': {
                    'base': home['port_base'],
                    'count': home['port_count'],
                },
                'tcp_ports': {
                    'base': home['tcp_port_base'],
                    'count': home['tcp_port_count'],
                },
            },
            'database': 'db.sqlite3',
            'home_console_port': home_console_port,
        }

        with open(output_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    profile_name = profile_dir.name
    print(f'\nDone. Configuration written to: {output_path}')
    print(f'  home_slug    : {home["slug"]}')
    print(f'  ssh_username : {home["ssh_username"]}')
    print(f'  ssh_host     : {ssh_host}:{home["ssh_port"]}')
    print(f'  port range   : {home["port_base"]} – {home["port_base"] + home["port_count"] - 1}')
    print(f'  console port : {home_console_port}')

    print('\nInitializing profile database...')
    result = _run_manage(output_path, 'migrate')

    if result.returncode == 0:
        print(f'\nStart this profile with:\n  python cah.py start {profile_name}')
    else:
        print(f'Warning: automatic migration failed:\n{result.stderr}', file=sys.stderr)
        print('\nRegistration succeeded, but you need to run migrations yourself before starting:')
        print(f'  HOME_CONFIG={output_path} python django/manage.py migrate')
        print(f'  python cah.py start {profile_name}')


def cmd_start(args):
    config_path = _profile_config_path(args.name)
    data = _load_yaml(config_path)

    port = args.port
    if port is None:
        port = data.get('home_console_port')
        if port is None:
            port = _pick_free_port(_HOME_DIR / 'providers')
            data['home_console_port'] = port
            with open(config_path, 'w') as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            print(f'Assigned port {port} to this profile (saved to config.yaml)')

    if not args.no_sync:
        print('Reconnecting existing tunnels...')
        _run_manage(config_path, 'sync_tunnels', capture=False)

    print(f'Starting Home Console for "{args.name}" on port {port}...')
    env = dict(os.environ, HOME_CONFIG=str(config_path))
    os.chdir(_MANAGE_PY.parent)
    os.execvpe(sys.executable, [sys.executable, str(_MANAGE_PY), 'runserver', f'0.0.0.0:{port}'], env)


def cmd_list(args):
    providers_dir = _HOME_DIR / 'providers'
    profile_dirs = sorted(p for p in providers_dir.iterdir() if p.is_dir()) if providers_dir.exists() else []

    rows = []
    for profile_dir in profile_dirs:
        config_path = profile_dir / 'config.yaml'
        if not config_path.exists():
            continue
        data = _load_yaml(config_path)
        cl = data.get('cloudlink', {})
        port = data.get('home_console_port')
        running = 'yes' if port and _is_port_open(port) else 'no'
        rows.append((profile_dir.name, cl.get('cloudserver_url', '-'), cl.get('home_slug', '-'),
                     str(port) if port else '-', running))

    if not rows:
        print('No profiles registered yet. Run: python cah.py register --token <token>')
        return

    header = ('NAME', 'CLOUD', 'SLUG', 'PORT', 'RUNNING')
    widths = [max(len(str(r[i])) for r in (header, *rows)) for i in range(len(header))]

    def fmt(row):
        return '  '.join(str(v).ljust(w) for v, w in zip(row, widths))

    print(fmt(header))
    for row in rows:
        print(fmt(row))


def cmd_remove(args):
    config_path = _profile_config_path(args.name)
    profile_dir = config_path.parent
    data = _load_yaml(config_path)
    cloudserver_url = data.get('cloudlink', {}).get('cloudserver_url', '(unknown cloud server)')

    if not args.yes:
        print(f'This will disconnect all tunnels, release the home slot on {cloudserver_url},')
        print(f'revoke this profile\'s API token, and permanently delete {profile_dir}')
        print('(database, certificates, SSH key).')
        if input('Continue? [y/N]: ').strip().lower() != 'y':
            print('Aborted.')
            return

    result = _run_manage(config_path, 'deregister')
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        print(f'\nDeregistration failed -- {profile_dir} was NOT deleted. '
              f'Fix the issue above and re-run to retry.', file=sys.stderr)
        sys.exit(1)

    shutil.rmtree(profile_dir)
    print(f'Removed profile "{args.name}".')


def main():
    parser = argparse.ArgumentParser(description='Manage CloudAtHome home-side profiles')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_register = subparsers.add_parser('register', help='Register this home with a cloud server')
    p_register.add_argument('name', type=str, nargs='?', default=None,
                             help='Profile directory name under home/providers/ (default: derived '
                                  'from the cloud server hostname)')
    p_register.add_argument('--cloudserver-url', default=None,
                             help='Base URL of the cloud server (default: home.yaml\'s '
                                  f'default_cloudserver_url, or {DEFAULT_CLOUDSERVER_URL})')
    p_register.add_argument('--token', required=True, help='API token, from the cloud server dashboard')
    p_register.add_argument('--public-key', type=Path, default=None,
                             help='Path to an existing SSH public key (default: generate a new '
                                  'dedicated keypair for this profile)')
    p_register.add_argument('--private-key', type=Path, default=None,
                             help='Path to an existing SSH private key (must be given together with --public-key)')
    p_register.add_argument('--output', '-o', type=Path, default=None,
                             help='Output path for config.yaml (default: home/providers/<name>/config.yaml)')
    p_register.set_defaults(func=cmd_register)

    p_start = subparsers.add_parser('start', help='Start the Home Console for a profile')
    p_start.add_argument('name', help='Profile name (see: python cah.py list)')
    p_start.add_argument('--port', type=int, default=None,
                          help='Port to serve on (default: auto-assigned and remembered per profile)')
    p_start.add_argument('--no-sync', action='store_true',
                          help='Skip automatically reconnecting existing tunnels on startup')
    p_start.set_defaults(func=cmd_start)

    p_list = subparsers.add_parser('list', help='List registered profiles')
    p_list.set_defaults(func=cmd_list)

    p_remove = subparsers.add_parser('remove', help='Deregister a profile from its cloud server and delete it locally')
    p_remove.add_argument('name', help='Profile name (see: python cah.py list)')
    p_remove.add_argument('--yes', '-y', action='store_true', help='Skip the confirmation prompt')
    p_remove.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
