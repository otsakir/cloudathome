#!/usr/bin/env python3
"""
manage_home.py — privileged tunnel-user management script

Runs privileged operations through subprocess.run(), and shares common
calculation functions (e.g. port-base math) with the rest of the app via the
module-level `tunnel_manager` singleton, imported in-process by Django code
that only needs to read config, not run privileged operations.

Fleet-size constants (MAX_HOME_COUNT and friends -- see Config) are an
install-time-only decision (see CLAUDE.md): scripts/generate_fleet_config.py
validates them once against .env and bakes them into
INSTALLED_FLEET_CONFIG_PATH, a file built into the django image at
`docker build` time (see django.dockerfile). Config reads that locked file,
not the process environment. This is deliberate: this script runs as root via
sudo, invoked by the unprivileged django user's own process
(ElevatedOperations, in tunnels/services.py); an environment variable is
something that process could always override per-call (subprocess.run(env=)
accepts an arbitrary dict), so trusting os.environ for a privileged decision
like "how many home slots exist" would make root's bounds only as trustworthy
as django's own environment. A root-owned file baked into the image at build
time isn't reachable from that process at all. Local dev and the standalone
pytest suite have no such file and fall back to FLEET_DEFAULTS.

Runs as root (via a tightly scoped sudoers rule). Django's ElevatedOperations
class invokes it with sudo; nothing else should call it directly.

High-level operations
---------------------
TunnelManager
  add / remove a system user for a home network:
    - create/delete the Linux user account (useradd/userdel)
    - install or revoke the SSH public key (~/.ssh/authorized_keys)
    - write or delete a per-user sshd Match block under sshd_config.d/
      (ForceCommand /bin/false, PermitTTY no, PermitListen on allocated ports)
    - add or remove the username from the shared AllowUsers directive
  reload  — send SIGHUP to sshd so config changes take effect

BandwidthManager
  set / unset a per-home egress bandwidth cap:
    - create/update/delete an HTB tc class on the outbound network interface
    - add/remove an iptables MARK rule that steers the home's tunnel ports
      into that tc class
"""

import argparse
import json
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(args, **kwargs):
    print(f'[manage_home] {" ".join(str(a) for a in args)}', file=sys.stderr)
    return subprocess.run(args, **kwargs)


# Fleet-size defaults -- the single copy scripts/generate_fleet_config.py also
# imports (from this module) for its own .env parsing, so the two never hand-drift
# apart. Only used as a fallback when INSTALLED_FLEET_CONFIG_PATH doesn't exist
# (local dev, the standalone pytest suite) -- see the module docstring above.
FLEET_DEFAULTS = {
    'MAX_HOME_COUNT': 10,
    'PORTS_PER_HOME': 10,
    'PORTS_PER_HOME_RESERVED': 100,
    'HOME_PORTS_BASE': 2000,
    'TCP_PUBLIC_PORTS_BASE': 10000,
    'TCP_PUBLIC_PORTS_PER_HOME': 10,
}

INSTALLED_FLEET_CONFIG_PATH = '/etc/cloudathome/fleet_config.json'


class FleetConfigError(ValueError):
    """Raised when fleet-size values are missing, non-positive, or mutually
    inconsistent."""


def validate_fleet_config(values):
    """Raises FleetConfigError if `values` (a dict keyed like FLEET_DEFAULTS) is
    invalid or internally inconsistent."""
    for key in FLEET_DEFAULTS:
        if key not in values:
            raise FleetConfigError(f'missing fleet config value: {key}')
        value = values[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise FleetConfigError(f'{key} must be a positive integer, got {value!r}')

    if values['PORTS_PER_HOME'] > values['PORTS_PER_HOME_RESERVED']:
        raise FleetConfigError(
            f"PORTS_PER_HOME ({values['PORTS_PER_HOME']}) must not exceed "
            f"PORTS_PER_HOME_RESERVED ({values['PORTS_PER_HOME_RESERVED']}) -- "
            "otherwise adjacent homes' tunnel port ranges overlap."
        )


def _load_installed_fleet_config():
    """Reads the fleet-size values locked in at install time by
    scripts/generate_fleet_config.py (baked into the image -- see
    django.dockerfile). Returns None if this process wasn't deployed via that
    install step; callers fall back to FLEET_DEFAULTS in that case.
    """
    try:
        with open(INSTALLED_FLEET_CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _fleet_value(installed, name):
    return installed[name] if installed is not None else FLEET_DEFAULTS[name]


_installed_fleet_config = _load_installed_fleet_config()


class Config:

    SSHD_CONFIGD_PATH = '/etc/ssh/sshd_config.d'
    SSHD_PID = '/var/run/sshd.pid'
    LISTENING_NETWORK_INTERFACE = '*'
    PUBLIC_KEY_STORAGE_PATH = '/var/tunnelagent/public_keys'
    NETWORK_INTERFACE = 'eth0'

    HOME_PREFIX = 'home'
    USERNAME_SUFFIX_PATTERN = '[a-z0-9_-]{1,20}'
    USERNAME_PATTERN = f'{HOME_PREFIX}([0-9]){{2}}_{USERNAME_SUFFIX_PATTERN}'

    MAX_HOME_COUNT = _fleet_value(_installed_fleet_config, 'MAX_HOME_COUNT')
    PORTS_PER_HOME = _fleet_value(_installed_fleet_config, 'PORTS_PER_HOME')
    PORTS_PER_HOME_RESERVED = _fleet_value(_installed_fleet_config, 'PORTS_PER_HOME_RESERVED')
    HOME_PORTS_BASE = _fleet_value(_installed_fleet_config, 'HOME_PORTS_BASE')
    TCP_PUBLIC_PORTS_BASE = _fleet_value(_installed_fleet_config, 'TCP_PUBLIC_PORTS_BASE')
    TCP_PUBLIC_PORTS_PER_HOME = _fleet_value(_installed_fleet_config, 'TCP_PUBLIC_PORTS_PER_HOME')

    BANDWIDTH_MIN_KBPS = 100
    BANDWIDTH_MAX_KBPS = 10_000_000

    def __init__(self):
        pass

    def set(self, **kwargs):
        for k in kwargs:
            if not hasattr(self, k):
                raise Exception(f'Invalid configuration attribute: {k}')
            setattr(self, k, kwargs[k])

    def __str__(self):
        return str({'PORTS_PER_HOME': self.PORTS_PER_HOME})


class HomeScriptError(Exception):
    def __init__(self, message):
        super().__init__(message)


class UserError(HomeScriptError):
    def __init__(self, message):
        super().__init__(message)


class BandwidthError(HomeScriptError):
    def __init__(self, message):
        super().__init__(message)


class TunnelManager:
    """Manages the lifecycle of SSH tunnel users: creates and removes system accounts,
    writes per-user sshd Match blocks, and maintains the AllowUsers directive."""

    def __init__(self, config: Config = None):
        self.config = config or Config()

    def add_username_to_allow_users(self, username: str):
        """Appends username to the AllowUsers directive. Returns False if already present."""
        config_file = open(f'{self.config.SSHD_CONFIGD_PATH}/01-allowed_users.conf', 'r+')

        content = config_file.read().strip()
        m = re.match(rf'AllowUsers\s(.*\s)?{username}(\s|$)', content)
        if m:
            print(f"user '{username}' is already in sshd_config AllowedUsers", file=sys.stderr)
            return False

        content = f'{content} {username}\n'
        config_file.seek(0)
        config_file.truncate()
        config_file.write(content)
        config_file.close()
        return True

    def remove_username_from_allow_users(self, username: str):
        """Removes username from the AllowUsers directive. Returns False if not found."""
        config_file = open(f'{self.config.SSHD_CONFIGD_PATH}/01-allowed_users.conf', 'r+')

        content = config_file.read().strip()
        m = re.match(rf'.* {username}( \S.*)?$', content)
        if not m:
            print(f"user '{username}' is not in sshd_config AllowedUsers", file=sys.stderr)
            return False

        content = re.sub(rf'\s+{username}(\s+\S+|$)', r'\1', content)
        config_file.seek(0)
        config_file.truncate()
        config_file.write(content)
        config_file.close()
        return True

    def get_user_sshdconfig_filename(self, username):
        return f'{self.config.SSHD_CONFIGD_PATH}/{username}.conf'

    def add_user_sshdconfig(self, username: str, port_base: int):
        """Writes a per-user Match block restricting the account to TCP port forwarding only."""
        config_file = open(self.get_user_sshdconfig_filename(username), 'w')
        config_file.write(f'Match User {username}\n')
        listen_ports = " ".join([
            f'{self.config.LISTENING_NETWORK_INTERFACE}:{port}'
            for port in range(port_base, port_base + self.config.PORTS_PER_HOME)
        ])
        config_file.write(f'    PermitListen {listen_ports}\n')
        config_file.write(f'    PermitTTY no\n')
        # ForceCommand is required even with PermitListen: without it the user could
        # still open exec channels (shell, sftp) over the same key.
        config_file.write(f'    ForceCommand /bin/false\n')
        config_file.close()

    def remove_user_sshdconfig(self, username: str):
        config_filename = self.get_user_sshdconfig_filename(username)
        try:
            os.remove(config_filename)
        except FileNotFoundError:
            print(f"error removing user specific ssh file '{config_filename}'", file=sys.stderr)

    def make_username(self, home_index: int, suffix: str) -> str:
        """Returns the canonical system username for a home slot, e.g. 'home03_alice'."""
        if 0 <= home_index < self.config.MAX_HOME_COUNT:
            m = re.match(rf'^{self.config.USERNAME_SUFFIX_PATTERN}$', suffix)
            if m:
                return f'{self.config.HOME_PREFIX}{home_index:02d}_{suffix}'
            else:
                raise UserError('invalid user suffix')
        else:
            raise UserError('bad home index')

    def get_home_port_base(self, home_id: int):
        # Stride is PORTS_PER_HOME_RESERVED (100), not PORTS_PER_HOME (10), giving each
        # home headroom to expand without renumbering all subsequent homes.
        return self.config.HOME_PORTS_BASE + home_id * self.config.PORTS_PER_HOME_RESERVED

    def get_home_tcp_public_port_base(self, home_id: int):
        return self.config.TCP_PUBLIC_PORTS_BASE + home_id * self.config.TCP_PUBLIC_PORTS_PER_HOME

    def create_tunnel_user(self, username: str, public_key_filename: str):
        """Creates a system user and installs the SSH public key from the staging area."""
        result = _run(['adduser', '-D', username])
        if result.returncode != 0:
            raise UserError('error creating user')

        os.mkdir(f'/home/{username}/.ssh')
        os.chmod(f'/home/{username}/.ssh', 0o700)
        shutil.chown(f'/home/{username}/.ssh', username, username)
        shutil.copy(
            f'{self.config.PUBLIC_KEY_STORAGE_PATH}/{public_key_filename}',
            f'/home/{username}/.ssh/authorized_keys',
        )
        os.chmod(f'/home/{username}/.ssh/authorized_keys', 0o600)
        shutil.chown(f'/home/{username}/.ssh/authorized_keys', username, username)

    def drop_tunnel_user(self, username: str):
        """Deletes the system user and removes its home directory."""
        result = _run(['deluser', username])
        if result.returncode != 0:
            print(f'could not remove user {username}, assuming already absent', file=sys.stderr)
        # Safety guard before rmtree: a wrong username here would silently delete an unrelated home directory.
        assert username.startswith(self.config.HOME_PREFIX)
        try:
            shutil.rmtree(f'/home/{username}/')
        except FileNotFoundError:
            print(f"error removing home directory for user '{username}'", file=sys.stderr)

    def get_sshd_pid(self):
        with open(self.config.SSHD_PID, 'r') as f:
            return int(f.read().strip())

    def reload_sshd_config(self):
        sshd_pid = self.get_sshd_pid()
        result = _run(['kill', '-HUP', str(sshd_pid)])
        if result.returncode != 0:
            raise HomeScriptError('error reloading sshd configuration')

    def update_tunnel_user_key(self, username: str, public_key_filename: str):
        """Replaces the authorized_keys file for an existing tunnel user."""
        dest = f'/home/{username}/.ssh/authorized_keys'
        shutil.copy(f'{self.config.PUBLIC_KEY_STORAGE_PATH}/{public_key_filename}', dest)
        os.chmod(dest, 0o600)
        shutil.chown(dest, username, username)

    def enable_user(self, username: str):
        """Unlocks the account for SSH key auth; adduser -D creates it with login disabled."""
        # Pass credentials via stdin to avoid shell=True with username interpolation.
        # '*' as the pre-encrypted hash disables password login while keeping key-based auth working.
        result = _run(
            ['chpasswd', '-e'],
            input=f'{username}:*\n',
            text=True,
        )
        if result.returncode != 0:
            raise UserError(f'error enabling user {username}')


class BandwidthManager:
    """Manages per-home egress bandwidth limits via tc HTB + iptables fwmark.

    Throttles the rate at which data leaves the home's tunnel ports toward HAProxy,
    which backpressures through the SSH connection to limit the home's upload rate.
    """

    def __init__(self, config: Config = None):
        self.config = config or Config()

    def _iface(self):
        return self.config.NETWORK_INTERFACE

    def _classid(self, home_id: int) -> str:
        # HTB class IDs within a major number must be non-zero; +1 maps home 0 → 1:1.
        return f'1:{home_id + 1}'

    def _mark(self, home_id: int) -> int:
        return home_id + 1

    def _port_range(self, home_id: int):
        # Returns inclusive [lo, hi]; iptables --sport requires a closed range.
        base = self.config.HOME_PORTS_BASE + home_id * self.config.PORTS_PER_HOME_RESERVED
        return base, base + self.config.PORTS_PER_HOME - 1

    def _ensure_root_qdisc(self):
        result = _run(
            ['/sbin/tc', 'qdisc', 'show', 'dev', self._iface()],
            capture_output=True, text=True,
        )
        if 'htb 1:' not in result.stdout:
            # 'default 999' routes unclassified traffic (homes without a bandwidth limit)
            # to a non-existent class, which HTB treats as best-effort pass-through.
            _run(
                ['/sbin/tc', 'qdisc', 'add', 'dev', self._iface(),
                 'root', 'handle', '1:', 'htb', 'default', '999'],
                check=True,
            )

    def _class_exists(self, home_id: int) -> bool:
        result = _run(
            ['/sbin/tc', 'class', 'show', 'dev', self._iface()],
            capture_output=True, text=True,
        )
        return self._classid(home_id) in result.stdout

    def set_bandwidth(self, home_id: int, rate_kbps: int):
        """Creates or updates the HTB class and iptables mark rule for home_id at rate_kbps."""
        self._ensure_root_qdisc()

        iface = self._iface()
        classid = self._classid(home_id)
        mark = self._mark(home_id)
        rate = f'{rate_kbps}kbit'
        port_lo, port_hi = self._port_range(home_id)

        if self._class_exists(home_id):
            _run(
                ['/sbin/tc', 'class', 'change', 'dev', iface,
                 'parent', '1:', 'classid', classid,
                 'htb', 'rate', rate, 'ceil', rate],
                check=True,
            )
        else:
            _run(
                ['/sbin/tc', 'class', 'add', 'dev', iface,
                 'parent', '1:', 'classid', classid,
                 'htb', 'rate', rate, 'ceil', rate],
                check=True,
            )
            _run(
                ['/sbin/tc', 'filter', 'add', 'dev', iface,
                 'parent', '1:', 'handle', str(mark), 'fw', 'classid', classid],
                check=True,
            )
            _run(
                ['/usr/sbin/iptables', '-t', 'mangle', '-A', 'OUTPUT',
                 '-p', 'tcp',
                 '--sport', f'{port_lo}:{port_hi}',
                 '-j', 'MARK', '--set-mark', str(mark)],
                check=True,
            )

    def unset_bandwidth(self, home_id: int):
        """Removes the HTB class and iptables mark rule for home_id. Safe to call when no limit is set."""
        iface = self._iface()
        classid = self._classid(home_id)
        mark = self._mark(home_id)
        port_lo, port_hi = self._port_range(home_id)

        # Remove the iptables mark rule first so no new packets get classified
        # into the tc class we are about to delete.
        _run(
            ['/usr/sbin/iptables', '-t', 'mangle', '-D', 'OUTPUT',
             '-p', 'tcp',
             '--sport', f'{port_lo}:{port_hi}',
             '-j', 'MARK', '--set-mark', str(mark)],
        )
        _run(
            ['/sbin/tc', 'filter', 'del', 'dev', iface,
             'parent', '1:', 'handle', str(mark), 'fw'],
        )
        if self._class_exists(home_id):
            _run(
                ['/sbin/tc', 'class', 'del', 'dev', iface, 'classid', classid],
                check=True,
            )


# --- Argument type validators ---

def _regex_type(pattern, description=''):
    def validate(value):
        if not re.match(pattern, value):
            raise argparse.ArgumentTypeError(f"Invalid value '{value}'. {description}")
        return value
    return validate


def _home_id_type(config: Config):
    def validate(value):
        try:
            home_id = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError('home_id must be an integer')
        if not (0 <= home_id < config.MAX_HOME_COUNT):
            raise argparse.ArgumentTypeError(
                f'home_id must be between 0 and {config.MAX_HOME_COUNT - 1}'
            )
        return home_id
    return validate


def _public_key_file_type(config: Config):
    def validate(filename):
        # Reject path separators and leading dots before any filesystem access.
        if not re.match(r'^[a-zA-Z0-9_-]+$', filename):
            raise argparse.ArgumentTypeError(
                'public key filename must contain only alphanumeric characters, underscores, and hyphens'
            )
        storage = Path(config.PUBLIC_KEY_STORAGE_PATH).resolve()
        path = (storage / filename).resolve()
        # Defense in depth: ensure resolved path stays within the storage directory.
        if not path.is_relative_to(storage):
            raise argparse.ArgumentTypeError('public key filename escapes storage directory')
        if not path.is_file():
            raise argparse.ArgumentTypeError(f'public key not found in {config.PUBLIC_KEY_STORAGE_PATH}')
        if not os.access(path, os.R_OK):
            raise argparse.ArgumentTypeError('public key file is not readable')
        return filename
    return validate


def _rate_kbps_type(config: Config):
    def validate(value):
        try:
            rate = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError('rate must be a positive integer (kbps)')
        if rate < config.BANDWIDTH_MIN_KBPS:
            raise argparse.ArgumentTypeError(
                f'rate must be at least {config.BANDWIDTH_MIN_KBPS} kbps'
            )
        if rate > config.BANDWIDTH_MAX_KBPS:
            raise argparse.ArgumentTypeError(
                f'rate must not exceed {config.BANDWIDTH_MAX_KBPS} kbps'
            )
        return rate
    return validate


def _build_parser(tunnel_mgr: TunnelManager, parser_class=None):
    config = tunnel_mgr.config
    parser = parser_class() if parser_class else argparse.ArgumentParser(prog='manage_home.py')
    subparsers = parser.add_subparsers(dest='command', required=True)

    suffix_type = _regex_type(
        f'^{config.USERNAME_SUFFIX_PATTERN}$',
        'Use lowercase letters, digits, hyphens, or underscores (max 20 chars).',
    )
    home_id_type = _home_id_type(config)
    pubkey_type = _public_key_file_type(config)

    # tunnel user commands
    add_p = subparsers.add_parser('add', help='Add SSH tunnel user for a home')
    add_p.add_argument('user_suffix', type=suffix_type)
    add_p.add_argument('home_id', type=home_id_type)
    add_p.add_argument('-p', '--public', type=pubkey_type, required=True,
                       help='Public key staging filename')

    remove_p = subparsers.add_parser('remove', help='Remove SSH tunnel user for a home')
    remove_p.add_argument('user_suffix', type=suffix_type)
    remove_p.add_argument('home_id', type=home_id_type)

    update_key_p = subparsers.add_parser('update-key', help='Replace SSH public key')
    update_key_p.add_argument('user_suffix', type=suffix_type)
    update_key_p.add_argument('home_id', type=home_id_type)
    update_key_p.add_argument('-p', '--public', type=pubkey_type, required=True,
                               help='Public key staging filename')

    subparsers.add_parser('reload', help='Reload sshd configuration')

    # bandwidth commands
    bw_p = subparsers.add_parser('bandwidth', help='Manage per-home bandwidth limits')
    bw_sub = bw_p.add_subparsers(dest='bw_command', required=True)

    bw_set = bw_sub.add_parser('set', help='Set or update bandwidth limit for a home')
    bw_set.add_argument('home_id', type=home_id_type)
    bw_set.add_argument('--rate', type=_rate_kbps_type(config), required=True,
                        help='Limit in kbps (e.g. 5000 for 5 Mbps)')

    bw_unset = bw_sub.add_parser('unset', help='Remove bandwidth limit for a home')
    bw_unset.add_argument('home_id', type=home_id_type)

    return parser


tunnel_manager = TunnelManager(Config())
bandwidth_manager = BandwidthManager(tunnel_manager.config)


if __name__ == '__main__':
    parser = _build_parser(tunnel_manager)
    args = parser.parse_args()

    if args.command == 'add':
        username = tunnel_manager.make_username(args.home_id, args.user_suffix)
        tunnel_manager.create_tunnel_user(username, args.public)
        tunnel_manager.enable_user(username)
        tunnel_manager.add_username_to_allow_users(username)
        port_base = tunnel_manager.get_home_port_base(args.home_id)
        tunnel_manager.add_user_sshdconfig(username, port_base)

    elif args.command == 'remove':
        username = tunnel_manager.make_username(args.home_id, args.user_suffix)
        tunnel_manager.drop_tunnel_user(username)
        tunnel_manager.remove_username_from_allow_users(username)
        tunnel_manager.remove_user_sshdconfig(username)
        bandwidth_manager.unset_bandwidth(args.home_id)

    elif args.command == 'update-key':
        username = tunnel_manager.make_username(args.home_id, args.user_suffix)
        tunnel_manager.update_tunnel_user_key(username, args.public)

    elif args.command == 'reload':
        tunnel_manager.reload_sshd_config()

    elif args.command == 'bandwidth':
        if args.bw_command == 'set':
            bandwidth_manager.set_bandwidth(args.home_id, args.rate)
        elif args.bw_command == 'unset':
            bandwidth_manager.unset_bandwidth(args.home_id)
