#!/usr/bin/env python3
"""Materializes fleet-size-derived install artifacts from .env.

Reads the fleet-size settings (MAX_HOME_COUNT, PORTS_PER_HOME,
PORTS_PER_HOME_RESERVED, HOME_PORTS_BASE, TCP_PUBLIC_PORTS_BASE,
TCP_PUBLIC_PORTS_PER_HOME) from .env, validates them, and:

  1. Writes the `backend tunnel_<port>` / `backend http_tunnel_<port>` stanzas
     -- one pair per SSH tunnel port, for every home -- between the
     `# BEGIN GENERATED BACKENDS` / `# END GENERATED BACKENDS` markers in
     docker/haproxy/haproxy.cfg. Everything outside those markers (frontends,
     defaults, the default backends) is left untouched.

  2. Derives TCP_PUBLIC_PORT_RANGE (= TCP_PUBLIC_PORTS_BASE spanning
     MAX_HOME_COUNT * TCP_PUBLIC_PORTS_PER_HOME ports) and writes it back into
     .env, so it's never a second, independently-hand-set value that can drift
     out of sync with the constants it's derived from.

  3. Writes the validated values to docker/django/fleet_config.json, which
     django.dockerfile bakes into the django image at build time. This is the
     only way these values reach manage_home.py -- see its module docstring
     for why it doesn't read them from the process environment.

Fleet-size sizing is an install-time-only decision (see CLAUDE.md): there is no
supported way to change it once homes have registered, since shrinking would
silently drop routing for homes above the new bound, and growing has never been
exercised against an already-migrated database. To guard against an accidental
re-run against a live instance, this script refuses to run once
src/var/db.sqlite3 exists (created the first time `migrate` runs) -- pass
--force only if you are certain (e.g. re-running after editing haproxy.cfg by
hand, before ever bringing the instance up).

Usage:
    python3 scripts/generate_fleet_config.py
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / '.env'
DEFAULT_CFG_FILE = REPO_ROOT / 'docker' / 'haproxy' / 'haproxy.cfg'
DEFAULT_INSTALLED_CONFIG_FILE = REPO_ROOT / 'docker' / 'django' / 'fleet_config.json'
DB_MARKER_FILE = REPO_ROOT / 'src' / 'var' / 'db.sqlite3'

BEGIN_MARKER = '# BEGIN GENERATED BACKENDS'
END_MARKER = '# END GENERATED BACKENDS'

# Fleet-size defaults and validation are defined once in manage_home.py (which has
# no Django dependency at module scope) and imported here, rather than duplicated,
# so the two never hand-drift apart.
sys.path.insert(0, str(REPO_ROOT / 'src'))
from tunnels.ssh.manage_home import FLEET_DEFAULTS as DEFAULTS, FleetConfigError, validate_fleet_config  # noqa: E402


def parse_env_file(path):
    """Minimal KEY=VALUE .env parser -- no quoting or multiline support,
    matching this repo's .env.example format."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        values[key.strip()] = value.strip()
    return values


def load_config(env_file):
    env_values = parse_env_file(env_file)
    config = {}
    for key, default in DEFAULTS.items():
        raw = env_values.get(key)
        if raw is None:
            config[key] = default
            continue
        try:
            config[key] = int(raw)
        except ValueError:
            sys.exit(f'error: {env_file}: {key}={raw!r} is not an integer')
    return config


def render_backends(config):
    home_bases = [
        config['HOME_PORTS_BASE'] + home_index * config['PORTS_PER_HOME_RESERVED']
        for home_index in range(config['MAX_HOME_COUNT'])
    ]

    lines = ['# Pre-created backends for all allocated tunnel ports '
             f'({config["MAX_HOME_COUNT"]} homes x {config["PORTS_PER_HOME"]} ports each)']
    for base in home_bases:
        for port in range(base, base + config['PORTS_PER_HOME']):
            lines.append(f'backend tunnel_{port}')
            lines.append(f'  server tunnel tunnelagent:{port}')
        lines.append('')

    lines.append('# HTTP backends for all tunnel ports (mode http, used for ACME challenges '
                  'and plain HTTP proxying)')
    for base in home_bases:
        for port in range(base, base + config['PORTS_PER_HOME']):
            lines.append(f'backend http_tunnel_{port}')
            lines.append('  mode http')
            lines.append(f'  server tunnel tunnelagent:{port}')
        lines.append('')

    return '\n'.join(lines).rstrip('\n') + '\n'


def splice(cfg_text, generated, cfg_file):
    pattern = re.compile(re.escape(BEGIN_MARKER) + r'\n.*?\n' + re.escape(END_MARKER), re.DOTALL)
    if not pattern.search(cfg_text):
        sys.exit(
            f'error: {cfg_file}: could not find {BEGIN_MARKER!r} / {END_MARKER!r} markers -- '
            'refusing to guess where generated content belongs'
        )
    replacement = f'{BEGIN_MARKER}\n{generated}{END_MARKER}'
    return pattern.sub(lambda _match: replacement, cfg_text, count=1)


def render_tcp_public_port_range(config):
    span = config['MAX_HOME_COUNT'] * config['TCP_PUBLIC_PORTS_PER_HOME']
    base = config['TCP_PUBLIC_PORTS_BASE']
    return f'{base}-{base + span - 1}'


def update_env_var(env_file, key, value):
    """Rewrites a single KEY=VALUE line in env_file, preserving every other line
    verbatim (comments, ordering, blank lines, other variables). Appends a new
    line at the end if the key isn't present yet."""
    if not env_file.exists():
        sys.exit(f'error: {env_file} not found -- copy .env.example to .env first')

    lines = env_file.read_text().splitlines()
    new_line = f'{key}={value}'
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#') or '=' not in stripped:
            continue
        existing_key, _, _ = stripped.partition('=')
        if existing_key.strip() == key:
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    env_file.write_text('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--env-file', type=Path, default=DEFAULT_ENV_FILE,
                         help=f'default: {DEFAULT_ENV_FILE}')
    parser.add_argument('--cfg-file', type=Path, default=DEFAULT_CFG_FILE,
                         help=f'default: {DEFAULT_CFG_FILE}')
    parser.add_argument('--installed-config-file', type=Path, default=DEFAULT_INSTALLED_CONFIG_FILE,
                         help=f'default: {DEFAULT_INSTALLED_CONFIG_FILE}')
    parser.add_argument('--force', action='store_true',
                         help='skip the already-initialized guard (dangerous -- see CLAUDE.md)')
    args = parser.parse_args()

    if DB_MARKER_FILE.exists() and DB_MARKER_FILE.stat().st_size > 0 and not args.force:
        sys.exit(
            f'error: {DB_MARKER_FILE} already exists -- this instance has already been initialized.\n'
            'Fleet-size sizing (MAX_HOME_COUNT and friends) is an install-time-only decision; '
            'changing it now would silently break routing for already-registered homes. '
            'See CLAUDE.md. Pass --force only if you are certain.'
        )

    if not args.cfg_file.exists():
        sys.exit(f'error: {args.cfg_file} not found')

    if not args.env_file.exists():
        sys.exit(f'error: {args.env_file} not found -- copy .env.example to .env first')

    config = load_config(args.env_file)
    try:
        validate_fleet_config(config)
    except FleetConfigError as e:
        sys.exit(f'error: {args.env_file}: {e}')

    generated = render_backends(config)
    new_cfg_text = splice(args.cfg_file.read_text(), generated, args.cfg_file)
    args.cfg_file.write_text(new_cfg_text)

    total = config['MAX_HOME_COUNT'] * config['PORTS_PER_HOME']
    print(f'Wrote {total} tunnel_* + {total} http_tunnel_* backend stanzas '
          f'({config["MAX_HOME_COUNT"]} homes x {config["PORTS_PER_HOME"]} ports each) to {args.cfg_file}')

    tcp_public_port_range = render_tcp_public_port_range(config)
    update_env_var(args.env_file, 'TCP_PUBLIC_PORT_RANGE', tcp_public_port_range)
    print(f'Set TCP_PUBLIC_PORT_RANGE={tcp_public_port_range} in {args.env_file} '
          f'(derived from TCP_PUBLIC_PORTS_BASE={config["TCP_PUBLIC_PORTS_BASE"]}, '
          f'MAX_HOME_COUNT={config["MAX_HOME_COUNT"]}, '
          f'TCP_PUBLIC_PORTS_PER_HOME={config["TCP_PUBLIC_PORTS_PER_HOME"]})')

    args.installed_config_file.parent.mkdir(parents=True, exist_ok=True)
    args.installed_config_file.write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')
    print(f'Wrote locked fleet config to {args.installed_config_file} '
          '(baked into the django image at build time -- see django.dockerfile)')


if __name__ == '__main__':
    main()
