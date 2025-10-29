import argparse
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Type


class Config:

    PORTS_PER_HOME = 10
    SSHD_CONFIGD_PATH = '/etc/ssh/sshd_config.d'
    SSHD_PID = '/var/run/sshd.pid'  # /var/run/sshd.pid for alpine
    LISTENING_NETWORK_INTERFACE = '127.0.0.1'
    # PUBLIC_KEY_STORAGE_PATH = '/tmp/public_keys'    # directory to transfer public keys to the script - for testing
    PUBLIC_KEY_STORAGE_PATH = '/var/tunnelagent/public_keys'    # directory to transfer public keys to the script

    # untested settings used in commandline invocation
    HOME_PREFIX = 'home'
    USERNAME_SUFFIX_PATTERN = '[a-z0-9_-]{1,20}'
    USERNAME_PATTERN = f'{HOME_PREFIX}([0-9]){2}_{USERNAME_SUFFIX_PATTERN}'

    MAX_HOME_COUNT = 10
    HOME_PORTS_BASE = 2000
    PORTS_PER_HOME_RESERVED = 100  # each home base port from next distance

    def __init__(self):
        pass


    def set(self, **kwargs):
        for k in kwargs:
            if not hasattr(self, k):
                raise Exception(f'Invalid configuration attribute: {k}')
            setattr(self, k, kwargs[k])

    def __str__(self):
        return str({'PORTS_PER_HOME': self.PORTS_PER_HOME})


class TunnelScriptError(Exception):
    """Error that occured in elevated privilege script"""

    def __init__(self, message):
        super().__init__(message)


class UserError(TunnelScriptError):
    def __init__(self, message):
        super().__init__(message)


class TunnelManager:

    def __init__(self, config: Config = Config()):
        self.config = config

    def add_username_to_allow_users(self, username: str):
        """Adds a POSIX username to the sshd_config AllowUsers directive"""

        config_file = open(f'{self.config.SSHD_CONFIGD_PATH}/01-allowed_users.conf', 'r+')

        content = config_file.read().strip()
        m = re.match(f'AllowUsers\s.* {username}( \S+)?$', content)
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
        """Removes a POSIX username from the sshd_config AllowUsers directive"""

        config_file = open(f'{self.config.SSHD_CONFIGD_PATH}/01-allowed_users.conf', 'r+')

        content = config_file.read().strip()
        m = re.match(f'.* {username}( \S.*)?$', content)
        if not m:
            print(f"user '{username}' is not in sshd_config AllowedUsers", file=sys.stderr)
            return False

        content = re.sub(f'\s+{username}(\s+\S+|$)', r'\1', content)
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
        for i in range(self.config.PORTS_PER_HOME):
            port = port_base + i
            config_file.write(f'    PermitListen {self.config.LISTENING_NETWORK_INTERFACE}:{port}\n')
        config_file.close()

    def remove_user_sshdconfig(self, username: str):
        config_filename = self.get_user_sshdconfig_filename(username)
        try:
            os.remove(config_filename)
        except FileNotFoundError as e:
            print(f"error removing user specific ssh file '{config_filename}'", file=sys.stderr)

    def make_username(self, home_index: int, suffix: str):
        """ Validates username suffix and builds up a proper username with prefix etc """

        if 0 <= home_index < self.config.MAX_HOME_COUNT:
            m = re.match(f'^{self.config.USERNAME_SUFFIX_PATTERN}$', suffix)
            if m:
                username = f'{self.config.HOME_PREFIX}{home_index:02d}_{suffix}'
                return username
            else:
                raise UserError('invalid user suffix')
        else:
            raise UserError('bad home index')


    def get_home_port_base(self, home_id: int):
        home_ports_base = self.config.HOME_PORTS_BASE + (args.home_id - 1) * self.config.PORTS_PER_HOME_RESERVED
        return home_ports_base


    # elevated privileges
    def create_tunnel_user(self, username: str, public_key_filename: str):

        # first create the user in the system
        # result = subprocess.run(['adduser', '--gecos', 'fullname', '--disabled-password', username])  # debian/ubuntu flavors
        result = subprocess.run(['adduser', '-D', 'fullname', username])  # alpine linux flavors
        if not result.returncode == 0:
            raise UserError("error creating user")

        # mkdir .ssh && chmod 700 .ssh && chown admin:admin .ssh
        os.mkdir(f'/home/{username}/.ssh')
        os.chmod(f'/home/{username}/.ssh', 0o700)
        shutil.chown(f'/home/{username}/.ssh', username, username)
        shutil.copy(f'{self.config.PUBLIC_KEY_STORAGE_PATH}/{public_key_filename}', f'/home/{username}/.ssh/authorized_keys')

        # chmod 600 authorized_keys & & chown admin: admin authorized_keys
        os.chmod(f'/home/{username}/.ssh/authorized_keys', 0o600)
        shutil.chown(f'/home/{username}/.ssh/authorized_keys', username, username)


    def drop_tunnel_user(self, username: str):
        result = subprocess.run(['deluser', username])
        if not result.returncode == 0:
            print(f'error removing user {username}', file=sys.stderr)
            # raise UserError("error removing user")
        # TODO remove user directory safely
        assert username.startswith(self.config.HOME_PREFIX) # make sure 'username' is that of a home_* user
        try:
            shutil.rmtree(f'/home/{username}/')
        except FileNotFoundError as e:
            print(f"error removing home directory for user '{username}'", file=sys.stderr)


    def get_sshd_pid(self):
        pid_file = open(self.config.SSHD_PID, 'r')
        content = pid_file.read()
        pid = int(content.strip())
        return pid

    def reload_sshd_config(self):
        sshd_pid = self.get_sshd_pid()
        result = subprocess.run(['kill', '-HUP', str(sshd_pid)])
        if result.returncode != 0:
            raise TunnelScriptError('error reloading sshd configuration')

    def get_parser(self, parser_class=None):
        # sudo python manage_tunnel.py add alice3 1 -p alice_public_key
        # sudo python manage_tunnel.py remove alice4 1
        parser = parser_class() if parser_class else argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest='command', required=True, help='Commands')

        add_parser = subparsers.add_parser('add', help='Add tunnel manager user')
        add_parser.add_argument('user_suffix', type=regex_type(f'^{self.config.USERNAME_SUFFIX_PATTERN}$',
                                                               'Use a proper POSIX username syntax.'))
        add_parser.add_argument('home_id', type=get_home_type(self.config))
        add_parser.add_argument('-p', '--public', type=get_public_key_file_type(self.config), help='public key temporary filename',
                                required=True)  # TODO better validate filename using a regex

        remove_parser = subparsers.add_parser('remove', help='Remove tunnel manager user')
        remove_parser.add_argument('user_suffix', type=regex_type(f'^{self.config.USERNAME_SUFFIX_PATTERN}$',
                                                                  'Use a proper POSIX username syntax.'))
        remove_parser.add_argument('home_id', type=get_home_type(self.config))

        return parser

# def enable_user(self, username):
#     # echo "admin:*" | chpasswd -e && cd /home/admin
#     result = subprocess.run(f'echo "{username}:*" | chpasswd -e', shell=True)
#     if result.returncode != 0:
#         raise UserError(f"error enabling user {username}")
#
#
# def disable_user(self, username):
#     result = subprocess.run(f'echo "{username}:!" | chpasswd -e', shell=True)
#     if result.returncode != 0:
#         raise UserError(f"error disabling user {username}")



# commandline interface

def regex_type(pattern, description=""):
    """Factory function to create a type that validates against regex"""
    def validate(value):
        if not re.match(pattern, value):
            raise argparse.ArgumentTypeError(
                f"Invalid value '{value}'. {description}"
            )
        return value
    return validate

def get_home_type(config: Config):
    def validate(value):
        home_id = int(value)
        if not (0 <= home_id < config.MAX_HOME_COUNT):
            raise argparse.ArgumentTypeError(f'home_id should be from 0 to {config.MAX_HOME_COUNT-1}')
        return home_id

    return validate


def get_public_key_file_type(config: Config):
    def public_key_file_type(filename):
        path_string = f'{config.PUBLIC_KEY_STORAGE_PATH}/{filename}'
        path = Path(path_string)
        if not path.is_file():
            raise argparse.ArgumentTypeError('public key path does not point to a file')
        if not os.access(path_string, os.R_OK):
            raise argparse.ArgumentTypeError('public key file is not readable')
        return filename
    return public_key_file_type


#print(args.command)
#print('args:', args)

if __name__ == '__main__':
    tunnel_manager = TunnelManager(Config())
    parser = tunnel_manager.get_parser()
    args = parser.parse_args()

    username = tunnel_manager.make_username(args.home_id, args.user_suffix)

    if args.command == 'add':
        tunnel_manager.create_tunnel_user(username, args.public)
        tunnel_manager.add_username_to_allow_users(username)
        home_port_base = tunnel_manager.get_home_port_base(args.home_id)
        tunnel_manager.add_user_sshdconfig(username, home_port_base)
        tunnel_manager.reload_sshd_config()
    elif args.command == 'remove':
        tunnel_manager.drop_tunnel_user(username)
        tunnel_manager.remove_username_from_allow_users(username)
        tunnel_manager.remove_user_sshdconfig(username)
        tunnel_manager.reload_sshd_config()
