from dataclasses import dataclass, field
from pathlib import Path
import os

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / 'config.yaml'


@dataclass
class SSHConfig:
    host: str
    port: int
    username: str
    private_key_path: str


@dataclass
class CertbotConfig:
    deploy_path: Path | None = None


@dataclass
class CloudConfig:
    cloudserver_url: str
    auth_token: str
    home_slug: str
    ssh: SSHConfig
    port_base: int
    port_count: int
    # Directory containing the config file; used to resolve relative paths.
    config_dir: Path = field(default_factory=Path.cwd)
    # Absolute path to the SQLite database file, resolved at load time.
    database: Path = field(default_factory=lambda: Path('db.sqlite3'))
    certbot: CertbotConfig = field(default_factory=CertbotConfig)


def load_config(path=None) -> CloudConfig:
    resolved = Path(os.environ.get('HOME_CONFIG', '') or path or _DEFAULT_CONFIG_PATH)
    try:
        with open(resolved) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f'CloudAtHome config not found at {resolved}. '
            'Run scripts/register_home.py to create it, or set the '
            'HOME_CONFIG environment variable to the correct path.'
        )
    try:
        cl = data['cloudlink']
        certbot_data = data.get('certbot') or {}
        config_dir = resolved.parent

        def resolve(p):
            path = Path(p)
            return path if path.is_absolute() else (config_dir / path).resolve()

        db_path = resolve(data.get('database') or 'db.sqlite3')

        raw_deploy = certbot_data.get('deploy_path')
        certbot_deploy = resolve(raw_deploy) if raw_deploy else None

        return CloudConfig(
            cloudserver_url=cl['cloudserver_url'],
            auth_token=cl['auth_token'],
            home_slug=cl['home_slug'],
            ssh=SSHConfig(**cl['ssh']),
            port_base=cl['ports']['base'],
            port_count=cl['ports']['count'],
            config_dir=config_dir,
            database=db_path,
            certbot=CertbotConfig(deploy_path=certbot_deploy),
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f'config.yaml is missing required field: {e}') from e


_config: CloudConfig | None = None


def get_config() -> CloudConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
