import argparse
import pytest
from tunnels.ssh.manage_home import (
    Config, TunnelManager, BandwidthManager, UserError,
    _build_parser, _public_key_file_type,
)


@pytest.fixture
def config(tmp_path):
    c = Config()
    sshd_dir = tmp_path / 'sshd_config.d'
    sshd_dir.mkdir()
    (sshd_dir / '01-allowed_users.conf').write_text('AllowUsers tester\n')
    c.SSHD_CONFIGD_PATH = str(sshd_dir)
    return c


@pytest.fixture
def tunnel_manager(config):
    return TunnelManager(config)


# --- make_username ---

def test_make_username(tunnel_manager):
    assert tunnel_manager.make_username(0, 'alice') == 'home00_alice'
    assert tunnel_manager.make_username(9, 'bob') == 'home09_bob'

def test_make_username_rejects_out_of_range_index(tunnel_manager, config):
    """no more than config.MAX_HOME_COUNT - make sure usernames abide by this"""
    with pytest.raises(UserError):
        tunnel_manager.make_username(config.MAX_HOME_COUNT, 'alice')

def test_make_username_rejects_invalid_suffix(tunnel_manager):
    with pytest.raises(UserError):
        tunnel_manager.make_username(0, 'alice!')

#
# # --- port allocation ---
#
def test_get_home_port_base(tunnel_manager):
    assert tunnel_manager.get_home_port_base(0) == 2000
    assert tunnel_manager.get_home_port_base(1) == 2100

def test_get_home_tcp_public_port_base(tunnel_manager):
    assert tunnel_manager.get_home_tcp_public_port_base(0) == 10000
    assert tunnel_manager.get_home_tcp_public_port_base(1) == 10010


# --- AllowUsers file manipulation ---

def test_add_username_to_allow_users(tunnel_manager, config):
    assert tunnel_manager.add_username_to_allow_users('alice') is True
    content = (config.SSHD_CONFIGD_PATH + '/01-allowed_users.conf')
    assert 'alice' in open(content).read()

def test_add_username_already_present(tunnel_manager):
    assert tunnel_manager.add_username_to_allow_users('tester') is False

def test_remove_username_from_allow_users(tunnel_manager, config):
    assert tunnel_manager.remove_username_from_allow_users('tester') is True
    content = open(config.SSHD_CONFIGD_PATH + '/01-allowed_users.conf').read()
    assert 'tester' not in content

def test_remove_username_not_present(tunnel_manager):
    assert tunnel_manager.remove_username_from_allow_users('nobody') is False


# --- per-user sshd config ---

@pytest.fixture
def sshdconfig_content(tunnel_manager, config):
    port_base = tunnel_manager.get_home_port_base(0)
    tunnel_manager.add_user_sshdconfig('alice', port_base)
    path = config.SSHD_CONFIGD_PATH + '/alice.conf'
    return open(path).read()


def test_sshdconfig_file_is_created(tunnel_manager, config):
    port_base = tunnel_manager.get_home_port_base(0)
    tunnel_manager.add_user_sshdconfig('alice', port_base)
    from pathlib import Path
    assert Path(config.SSHD_CONFIGD_PATH + '/alice.conf').exists()

def test_sshdconfig_match_user_directive(sshdconfig_content):
    assert 'Match User alice' in sshdconfig_content

def test_sshdconfig_force_command(sshdconfig_content):
    assert 'ForceCommand /bin/false' in sshdconfig_content

def test_sshdconfig_no_tty(sshdconfig_content):
    assert 'PermitTTY no' in sshdconfig_content

def test_sshdconfig_permit_listen_port_count(sshdconfig_content, config):
    line = next(l for l in sshdconfig_content.splitlines() if 'PermitListen' in l)
    ports = line.split()[1:]  # drop 'PermitListen'
    assert len(ports) == config.PORTS_PER_HOME

def test_sshdconfig_permit_listen_port_range(sshdconfig_content, tunnel_manager):
    line = next(l for l in sshdconfig_content.splitlines() if 'PermitListen' in l)
    port_numbers = [int(p.split(':')[1]) for p in line.split()[1:]]
    port_base = tunnel_manager.get_home_port_base(0)
    assert port_numbers == list(range(port_base, port_base + tunnel_manager.config.PORTS_PER_HOME))

def test_sshdconfig_remove_deletes_file(tunnel_manager, config):
    port_base = tunnel_manager.get_home_port_base(0)
    tunnel_manager.add_user_sshdconfig('alice', port_base)
    tunnel_manager.remove_user_sshdconfig('alice')
    from pathlib import Path
    assert not Path(config.SSHD_CONFIGD_PATH + '/alice.conf').exists()

def test_sshdconfig_remove_nonexistent_does_not_raise(tunnel_manager):
    tunnel_manager.remove_user_sshdconfig('ghost')


# --- AllowUsers edge cases ---

def test_add_username_does_not_match_substring(tunnel_manager):
    # 'test' must not be considered present just because 'tester' is in the file
    assert tunnel_manager.add_username_to_allow_users('test') is True

def test_add_username_written_to_file(tunnel_manager, config):
    tunnel_manager.add_username_to_allow_users('alice')
    content = open(config.SSHD_CONFIGD_PATH + '/01-allowed_users.conf').read()
    assert 'AllowUsers tester alice' in content

def test_remove_username_preserves_other_users(tunnel_manager, config):
    tunnel_manager.add_username_to_allow_users('alice')
    tunnel_manager.remove_username_from_allow_users('tester')
    content = open(config.SSHD_CONFIGD_PATH + '/01-allowed_users.conf').read()
    assert 'tester' not in content
    assert 'alice' in content

def test_remove_only_user_leaves_empty_directive(tunnel_manager, config):
    tunnel_manager.remove_username_from_allow_users('tester')
    content = open(config.SSHD_CONFIGD_PATH + '/01-allowed_users.conf').read()
    assert content.strip() == 'AllowUsers'


# --- port allocation across all homes ---

@pytest.mark.parametrize('home_id', range(10))
def test_get_home_port_base_all_homes(tunnel_manager, home_id):
    assert tunnel_manager.get_home_port_base(home_id) == 2000 + home_id * 100

@pytest.mark.parametrize('home_id', range(10))
def test_get_home_tcp_public_port_base_all_homes(tunnel_manager, home_id):
    assert tunnel_manager.get_home_tcp_public_port_base(home_id) == 10000 + home_id * 10


# --- BandwidthManager pure helpers ---

@pytest.fixture
def bandwidth_manager(config):
    return BandwidthManager(config)


@pytest.mark.parametrize('home_id', range(10))
def test_bandwidth_classid(bandwidth_manager, home_id):
    assert bandwidth_manager._classid(home_id) == f'1:{home_id + 1}'

@pytest.mark.parametrize('home_id', range(10))
def test_bandwidth_mark(bandwidth_manager, home_id):
    assert bandwidth_manager._mark(home_id) == home_id + 1

@pytest.mark.parametrize('home_id', range(10))
def test_bandwidth_port_range(bandwidth_manager, config, home_id):
    lo, hi = bandwidth_manager._port_range(home_id)
    expected_lo = config.HOME_PORTS_BASE + home_id * config.PORTS_PER_HOME_RESERVED
    assert lo == expected_lo
    assert hi == expected_lo + config.PORTS_PER_HOME - 1


# --- argument parser ---

class _ParseError(Exception):
    pass


class _StrictParser(argparse.ArgumentParser):
    """Raises _ParseError instead of sys.exit so tests can assert on bad input."""
    def error(self, message):
        raise _ParseError(message)


@pytest.fixture
def parser(tunnel_manager, config, tmp_path):
    keys_dir = tmp_path / 'keys'
    keys_dir.mkdir()
    config.PUBLIC_KEY_STORAGE_PATH = str(keys_dir)
    return _build_parser(tunnel_manager, _StrictParser)


def test_parser_reload(parser):
    args = parser.parse_args(['reload'])
    assert args.command == 'reload'

def test_parser_bandwidth_set(parser):
    args = parser.parse_args(['bandwidth', 'set', '0', '--rate', '5000'])
    assert args.bw_command == 'set'
    assert args.home_id == 0
    assert args.rate == 5000

def test_parser_bandwidth_set_rate_below_min(parser):
    with pytest.raises(_ParseError):
        parser.parse_args(['bandwidth', 'set', '0', '--rate', '50'])

def test_parser_bandwidth_unset(parser):
    args = parser.parse_args(['bandwidth', 'unset', '3'])
    assert args.bw_command == 'unset'
    assert args.home_id == 3

def test_parser_update_key(parser, tmp_path):
    (tmp_path / 'keys' / 'mykey').write_text('ssh-ed25519 AAAA...')
    args = parser.parse_args(['update-key', 'alice', '0', '-p', 'mykey'])
    assert args.command == 'update-key'
    assert args.user_suffix == 'alice'
    assert args.home_id == 0

def test_parser_invalid_home_id(parser):
    with pytest.raises(_ParseError):
        parser.parse_args(['bandwidth', 'set', '99', '--rate', '5000'])


# --- _public_key_file_type validator ---

@pytest.fixture
def keys_dir(config, tmp_path):
    d = tmp_path / 'keys'
    d.mkdir()
    config.PUBLIC_KEY_STORAGE_PATH = str(d)
    return d


def test_pubkey_validator_accepts_valid_file(keys_dir, config):
    (keys_dir / 'mykey').write_text('ssh-ed25519 AAAA...')
    validate = _public_key_file_type(config)
    assert validate('mykey') == 'mykey'

def test_pubkey_validator_rejects_path_traversal(keys_dir, config):
    validate = _public_key_file_type(config)
    with pytest.raises(argparse.ArgumentTypeError):
        validate('../secret')

def test_pubkey_validator_rejects_path_separator(keys_dir, config):
    validate = _public_key_file_type(config)
    with pytest.raises(argparse.ArgumentTypeError):
        validate('subdir/key')

def test_pubkey_validator_rejects_missing_file(keys_dir, config):
    validate = _public_key_file_type(config)
    with pytest.raises(argparse.ArgumentTypeError):
        validate('nonexistent')
