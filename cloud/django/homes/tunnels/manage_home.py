#!/usr/bin/env python3

import argparse
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(args, **kwargs):
    print(f'[manage_home] {" ".join(str(a) for a in args)}', file=sys.stderr)
    return subprocess.run(args, **kwargs)


class Config:

    PORTS_PER_HOME = 10
    SSHD_CONFIGD_PATH = '/etc/ssh/sshd_config.d'
    SSHD_PID = '/var/run/sshd.pid'
    LISTENING_NETWORK_INTERFACE = '*'
    PUBLIC_KEY_STORAGE_PATH = '/var/tunnelagent/public_keys'
    NETWORK_INTERFACE = 'eth0'

    HOME_PREFIX = 'home'
    USERNAME_SUFFIX_PATTERN = '[a-z0-9_-]{1,20}'
    USERNAME_PATTERN = f'{HOME_PREFIX}([0-9]){{2}}_{USERNAME_SUFFIX_PATTERN}'

    MAX_HOME_COUNT = 10
    HOME_PORTS_BASE = 2000
    PORTS_PER_HOME_RESERVED = 100

    TCP_PUBLIC_PORTS_BASE = 10000
    TCP_PUBLIC_PORTS_PER_HOME = 100

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

    def __init__(self, config: Config = None):
        self.config = config or Config()

    def add_username_to_allow_users(self, username: str):
        config_file = open(f'{self.config.SSHD_CONFIGD_PATH}/01-allowed_users.conf', 'r+')

        content = config_file.read().strip()
        m = re.match(rf'AllowUsers\s.* {username}( \S+)?$', content)
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
        config_file = open(self.get_user_sshdconfig_filename(username), 'w')
        config_file.write(f'Match User {username}\n')
        listen_ports = " ".join([
            f'{self.config.LISTENING_NETWORK_INTERFACE}:{port}'
            for port in range(port_base, port_base + self.config.PORTS_PER_HOME)
        ])
        config_file.write(f'    PermitListen {listen_ports}\n')
        config_file.write(f'    PermitTTY no\n')
        config_file.write(f'    ForceCommand /bin/false\n')
        config_file.close()

    def remove_user_sshdconfig(self, username: str):
        config_filename = self.get_user_sshdconfig_filename(username)
        try:
            os.remove(config_filename)
        except FileNotFoundError:
            print(f"error removing user specific ssh file '{config_filename}'", file=sys.stderr)

    def make_username(self, home_index: int, suffix: str) -> str:
        if 0 <= home_index < self.config.MAX_HOME_COUNT:
            m = re.match(rf'^{self.config.USERNAME_SUFFIX_PATTERN}$', suffix)
            if m:
                return f'{self.config.HOME_PREFIX}{home_index:02d}_{suffix}'
            else:
                raise UserError('invalid user suffix')
        else:
            raise UserError('bad home index')

    def get_home_port_base(self, home_id: int):
        return self.config.HOME_PORTS_BASE + home_id * self.config.PORTS_PER_HOME_RESERVED

    def get_home_tcp_public_port_base(self, home_id: int):
        return self.config.TCP_PUBLIC_PORTS_BASE + home_id * self.config.TCP_PUBLIC_PORTS_PER_HOME

    def create_tunnel_user(self, username: str, public_key_filename: str):
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
        result = _run(['deluser', username])
        if result.returncode != 0:
            print(f'could not remove user {username}, assuming already absent', file=sys.stderr)
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
        dest = f'/home/{username}/.ssh/authorized_keys'
        shutil.copy(f'{self.config.PUBLIC_KEY_STORAGE_PATH}/{public_key_filename}', dest)
        os.chmod(dest, 0o600)
        shutil.chown(dest, username, username)

    def enable_user(self, username: str):
        # Pass credentials via stdin to avoid shell=True with username interpolation.
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
        return f'1:{home_id + 1}'

    def _mark(self, home_id: int) -> int:
        return home_id + 1

    def _port_range(self, home_id: int):
        base = self.config.HOME_PORTS_BASE + home_id * self.config.PORTS_PER_HOME_RESERVED
        return base, base + self.config.PORTS_PER_HOME - 1

    def _ensure_root_qdisc(self):
        result = _run(
            ['/sbin/tc', 'qdisc', 'show', 'dev', self._iface()],
            capture_output=True, text=True,
        )
        if 'htb 1:' not in result.stdout:
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
        iface = self._iface()
        classid = self._classid(home_id)
        mark = self._mark(home_id)
        port_lo, port_hi = self._port_range(home_id)

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
