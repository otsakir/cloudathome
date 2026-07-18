#!/usr/bin/env python3
"""
Register this home with a CloudAtHome cloud server and write config.yaml.

Usage:
    python register_home.py \\
        --cloudserver-url https://cloud.example.com \\
        --token <api-token-from-the-dashboard> \\
        [--name myhome]

By default a dedicated SSH keypair is generated for this profile; pass both
--public-key and --private-key together to bring your own instead.

Without --output, each registration gets its own profile directory under
home/providers/<name>/, so the same client can register with multiple cloud
servers side by side (run one `manage.py runserver` per profile, each with
HOME_CONFIG pointed at its own config.yaml). Use --name to choose the
directory name; without it, one is suggested from the cloud server's
hostname.
"""
import argparse
import os
import re
import shutil
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

# home/ directory (one level up from scripts/)
_HOME_DIR = Path(__file__).resolve().parent.parent


def _validate_profile_name(name):
    """Guard against unsafe directory names: must be a single, visible path component."""
    if not name or '/' in name or os.sep in name or name.startswith('.'):
        print(
            f"Error: invalid profile name '{name}': must be a plain name, "
            f"no '/' and no leading dot",
            file=sys.stderr,
        )
        sys.exit(1)


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


def _generate_keypair(private_key_path):
    """Generate a fresh ed25519 keypair at private_key_path. Returns the public key content."""
    result = subprocess.run(
        ['ssh-keygen', '-t', 'ed25519', '-f', str(private_key_path), '-N', ''],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f'Error: ssh-keygen failed:\n{result.stderr}', file=sys.stderr)
        sys.exit(1)
    private_key_path.chmod(0o600)
    return private_key_path.with_suffix('.pub').read_text().strip()


def main():
    parser = argparse.ArgumentParser(description='Register home with CloudAtHome cloud server')
    parser.add_argument('--cloudserver-url', required=True, help='Base URL of the cloud server')
    parser.add_argument('--token', required=True, help='API token, from the cloud server dashboard')
    parser.add_argument('--public-key', type=Path, default=None,
                        help='Path to an existing SSH public key (default: generate a new dedicated keypair for this profile)')
    parser.add_argument('--private-key', type=Path, default=None,
                        help='Path to an existing SSH private key (must be given together with --public-key)')
    parser.add_argument('--name', type=str, default=None,
                        help='Profile directory name under home/providers/ (default: derived from the cloud server hostname)')
    parser.add_argument('--output', '-o', type=Path, default=None,
                        help='Output path for config.yaml (default: home/providers/<name>/config.yaml)')
    args = parser.parse_args()

    if bool(args.public_key) != bool(args.private_key):
        print('Error: --public-key and --private-key must be given together', file=sys.stderr)
        sys.exit(1)

    base_url = args.cloudserver_url.rstrip('/')
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
                print(f'Error: profile already exists: {profile_dir}', file=sys.stderr)
                sys.exit(1)
        else:
            profile_dir = providers_dir / _suggest_profile_name(providers_dir, ssh_host)
        output_path = profile_dir / 'config.yaml'

    with tempfile.TemporaryDirectory() as tmpdir:
        if args.public_key:
            try:
                public_key_content = args.public_key.read_text().strip()
            except FileNotFoundError:
                print(f'Error: public key file not found: {args.public_key}', file=sys.stderr)
                sys.exit(1)
            if not args.private_key.exists():
                print(f'Error: private key file not found: {args.private_key}', file=sys.stderr)
                sys.exit(1)
            private_key_path = args.private_key.resolve()
        else:
            print('Generating a dedicated SSH keypair for this profile...')
            tmp_private_key = Path(tmpdir) / 'ssh_key'
            public_key_content = _generate_keypair(tmp_private_key)
            private_key_path = None  # finalized below, once profile_dir exists

        # Step: register home
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
            print(f'Error: home registration failed: {e}', file=sys.stderr)
            sys.exit(1)

        home = resp.json()

        profile_dir.mkdir(parents=True, exist_ok=True)

        if private_key_path is None:
            private_key_path = profile_dir / 'ssh_key'
            shutil.move(str(tmp_private_key), str(private_key_path))
            shutil.move(str(tmp_private_key) + '.pub', str(private_key_path) + '.pub')
            private_key_path = private_key_path.resolve()

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
        }

        with open(output_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f'\nDone. Configuration written to: {output_path}')
    print(f'  home_slug    : {home["slug"]}')
    print(f'  ssh_username : {home["ssh_username"]}')
    print(f'  ssh_host     : {ssh_host}:{home["ssh_port"]}')
    print(f'  port range   : {home["port_base"]} – {home["port_base"] + home["port_count"] - 1}')
    print(f'\nStart this profile with:')
    print(f'  HOME_CONFIG={output_path} python manage.py runserver 0.0.0.0:<port>')


if __name__ == '__main__':
    main()
