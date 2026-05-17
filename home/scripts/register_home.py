#!/usr/bin/env python3
"""
Register this home with a CloudAtHome cloud server and write config.yaml.

Usage:
    python register_home.py \\
        --cloudserver-url https://cloud.example.com \\
        --username alice \\
        --password secret \\
        --public-key ~/.ssh/cloudathome_ed25519.pub \\
        --private-key ~/.ssh/cloudathome_ed25519 \\
        [--ssh-port 8022] \\
        [--output /path/to/config.yaml]

Run generate_keys.py first if you do not yet have a key pair.
"""
import argparse
import sys
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

# Default output path: home/config.yaml (two levels up from scripts/)
_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = _SCRIPTS_DIR.parent / 'config.yaml'


def main():
    parser = argparse.ArgumentParser(description='Register home with CloudAtHome cloud server')
    parser.add_argument('--cloudserver-url', required=True, help='Base URL of the cloud server')
    parser.add_argument('--username', required=True, help='Cloud server account username')
    parser.add_argument('--password', required=True, help='Cloud server account password')
    parser.add_argument('--public-key', required=True, type=Path,
                        help='Path to the SSH public key file')
    parser.add_argument('--private-key', required=True, type=Path,
                        help='Path to the SSH private key file')
    parser.add_argument('--ssh-port', type=int, default=8022,
                        help='SSH port on the cloud server (default: 8022)')
    parser.add_argument('--output', '-o', type=Path, default=DEFAULT_OUTPUT,
                        help=f'Output path for config.yaml (default: {DEFAULT_OUTPUT})')
    args = parser.parse_args()

    base_url = args.cloudserver_url.rstrip('/')

    # Read public key
    try:
        public_key_content = args.public_key.read_text().strip()
    except FileNotFoundError:
        print(f'Error: public key file not found: {args.public_key}', file=sys.stderr)
        sys.exit(1)

    if not args.private_key.exists():
        print(f'Error: private key file not found: {args.private_key}', file=sys.stderr)
        sys.exit(1)

    # Step 1: authenticate
    print('Authenticating with cloud server...')
    try:
        resp = requests.post(
            f'{base_url}/api/auth/authtoken/',
            json={'username': args.username, 'password': args.password},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f'Error: authentication failed: {e}', file=sys.stderr)
        sys.exit(1)

    token = resp.json().get('token')
    if not token:
        print(f'Error: no token in response: {resp.text}', file=sys.stderr)
        sys.exit(1)

    # Step 2: register home
    print('Registering home...')
    try:
        resp = requests.post(
            f'{base_url}/api/homes/',
            json={'public_key': public_key_content},
            headers={'Authorization': f'Token {token}'},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f'Error: home registration failed: {e}', file=sys.stderr)
        sys.exit(1)

    home = resp.json()

    ssh_host = urlparse(base_url).hostname

    config = {
        'cloudlink': {
            'cloudserver_url': base_url,
            'auth_token': token,
            'home_slug': home['slug'],
            'ssh': {
                'host': ssh_host,
                'port': args.ssh_port,
                'username': home['ssh_username'],
                'private_key_path': str(args.private_key.resolve()),
            },
            'ports': {
                'base': home['port_base'],
                'count': home['port_count'],
            },
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f'\nDone. Configuration written to: {args.output}')
    print(f'  home_slug    : {home["slug"]}')
    print(f'  ssh_username : {home["ssh_username"]}')
    print(f'  ssh_host     : {ssh_host}:{args.ssh_port}')
    print(f'  port range   : {home["port_base"]} – {home["port_base"] + home["port_count"] - 1}')
    print(f'\nYou can now start the home Django server.')


if __name__ == '__main__':
    main()
