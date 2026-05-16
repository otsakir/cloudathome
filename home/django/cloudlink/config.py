from dataclasses import dataclass
from pathlib import Path
import os

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / 'config' / 'cloudlink.yaml'


@dataclass
class SSHConfig:
    host: str
    port: int
    username: str
    private_key_path: str


@dataclass
class CloudConfig:
    cloudserver_url: str
    auth_token: str
    home_slug: str
    ssh: SSHConfig
    port_base: int
    port_count: int


def load_config(path=None) -> CloudConfig:
    resolved = Path(os.environ.get('CLOUDLINK_CONFIG', '') or path or _DEFAULT_CONFIG_PATH)
    try:
        with open(resolved) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f'CloudAtHome config not found at {resolved}. '
            'Run scripts/register_home.py to create it, or set the '
            'CLOUDLINK_CONFIG environment variable to the correct path.'
        )
    try:
        return CloudConfig(
            cloudserver_url=data['cloudserver_url'],
            auth_token=data['auth_token'],
            home_slug=data['home_slug'],
            ssh=SSHConfig(**data['ssh']),
            port_base=data['ports']['base'],
            port_count=data['ports']['count'],
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f'cloudlink.yaml is missing required field: {e}') from e


_config: CloudConfig | None = None


def get_config() -> CloudConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
