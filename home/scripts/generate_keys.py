#!/usr/bin/env python3
"""
Generate a dedicated SSH ed25519 key pair for CloudAtHome tunnel use.

Usage:
    python generate_keys.py [--output PATH] [--force]

The public key is printed to stdout so it can be passed directly to
register_home.py:

    python generate_keys.py | python register_home.py --public-key /dev/stdin ...
"""
import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_KEY_PATH = Path.home() / '.ssh' / 'cloudathome_ed25519'


def main():
    parser = argparse.ArgumentParser(description='Generate SSH key pair for CloudAtHome')
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=DEFAULT_KEY_PATH,
        help=f'Path for the private key (default: {DEFAULT_KEY_PATH})',
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Overwrite existing key pair without prompting',
    )
    args = parser.parse_args()

    private_key = args.output
    public_key = private_key.with_suffix('.pub')

    if private_key.exists() and not args.force:
        print(
            f'Error: {private_key} already exists. Use --force to overwrite.',
            file=sys.stderr,
        )
        sys.exit(1)

    private_key.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ['ssh-keygen', '-t', 'ed25519', '-f', str(private_key), '-N', ''],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f'Error: ssh-keygen failed:\n{result.stderr}', file=sys.stderr)
        sys.exit(1)

    private_key.chmod(0o600)
    print(public_key.read_text(), end='')


if __name__ == '__main__':
    main()
