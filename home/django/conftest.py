import os
import pytest


@pytest.fixture(autouse=True)
def cloudlink_config(tmp_path, monkeypatch):
    """Provide a minimal valid cloudlink.yaml so get_config() succeeds during tests."""
    config = tmp_path / 'cloudlink.yaml'
    config.write_text(
        'cloudserver_url: https://cloud.example.com\n'
        'auth_token: testtoken\n'
        'home_slug: testslug\n'
        'ssh:\n'
        '  host: cloud.example.com\n'
        '  port: 22\n'
        '  username: home00_test\n'
        '  private_key_path: /tmp/test_key\n'
        'ports:\n'
        '  base: 2000\n'
        '  count: 10\n'
    )
    monkeypatch.setenv('CLOUDLINK_CONFIG', str(config))
    # reset the cached singleton so each test gets a fresh load
    import cloudlink.config as cfg_module
    monkeypatch.setattr(cfg_module, '_config', None)
