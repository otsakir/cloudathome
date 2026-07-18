from cloudlink.config import get_config
from domains.services import CertbotService


def test_certbot_dir_resolves_relative_to_config_dir(tmp_path):
    cfg = get_config()
    assert cfg.certbot_dir == tmp_path / 'certbot'


def test_certbot_service_dirs_follow_active_config(tmp_path):
    assert CertbotService._config_dir() == tmp_path / 'certbot' / 'config'
    assert CertbotService._work_dir() == tmp_path / 'certbot' / 'work'
    assert CertbotService._logs_dir() == tmp_path / 'certbot' / 'logs'
