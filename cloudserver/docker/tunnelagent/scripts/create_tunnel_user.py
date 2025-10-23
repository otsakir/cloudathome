#!/usr/bin/env python3
import subprocess
import shutil
import re
import os


HOME_PREFIX = 'home'    # string literal used when genereting POSIC usernames for home users
MAX_HOME_COUNT = 10     # number of available home slots
USERNAME_SUFFIX_PATTERN = '[a-z0-9_-]{1,20}'
USERNAME_PATTERN = f'{HOME_PREFIX}([0-9]){2}_{USERNAME_SUFFIX_PATTERN}'


class UserError(Exception):
    def __init__(self, message):
        super().__init__(message)


def make_username(home_index: int, suffix: str):
    """ Validates username suffix and builds up a proper username with prefix etc """

    if 0 <= home_index < MAX_HOME_COUNT:
        m = re.match(f'^{USERNAME_SUFFIX_PATTERN}$', suffix)
        if m:
            username = f'{HOME_PREFIX}{home_index:02d}_{suffix}'
            return username
        else:
            raise UserError('invalid user suffix')
    else:
        raise UserError('bad home index')


# tests
#
# assert make_username(1, 'alice') == 'home01_alice'  # test actual username generation
# assert make_username(9, 'nick_the-greek21')  # test validation
# assert not make_username(MAX_HOME_COUNT, 'alice')  # bad home index
# assert not make_username(1, '01234567890123456789_')  # too long


def create_tunnel_user(home_index: int, user_suffix: str, public_key_filename: str):

    # first create the user in the system
    username = make_username(home_index, user_suffix)
    result = subprocess.run(['adduser', '--gecos', 'fullname', '--disabled-password', username])
    if not result.returncode == 0:
        raise UserError("error creating user")

    # mkdir .ssh && chmod 700 .ssh && chown admin:admin .ssh
    os.mkdir(f'/home/{username}/.ssh')
    os.chmod(f'/home/{username}/.ssh', 0o700)
    shutil.chown(f'/home/{username}/.ssh', username, username)
    shutil.copy(public_key_filename, f'/home/{username}/.ssh/authorized_keys')

    # chmod 600 authorized_keys & & chown admin: admin authorized_keys
    os.chmod(f'/home/{username}/.ssh/authorized_keys', 0o600)
    shutil.chown(f'/home/{username}/.ssh/authorized_keys', username, username)


def enable_user(home_index: int, user_suffix: str):
    username = make_username(home_index, user_suffix)

    # echo "admin:*" | chpasswd -e && cd /home/admin
    result = subprocess.run(f'echo "{username}:*" | chpasswd -e', shell=True)
    if result.returncode != 0:
        raise UserError(f"error enabling user {username}")


def disable_user(home_index: int, user_suffix: str):
    username = make_username(home_index, user_suffix)

    result = subprocess.run(f'echo "{username}:!" | chpasswd -e', shell=True)
    if result.returncode != 0:
        raise UserError(f"error disabling user {username}")


def drop_tunnel_user(home_index: int, user_suffix: str):
    username = make_username(home_index, user_suffix)
    # print(f'removing home user {username}')
    result = subprocess.run(['deluser', username])
    if not result.returncode == 0:
        raise UserError("error removing user")
    # TODO remove user directory safely


