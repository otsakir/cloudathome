import pytest
from tunnels.ssh.manage_home import Config, TunnelManager, UserError


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
