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
class FeaturesConfig:
    lan_forwarding: bool = False


@dataclass
class CloudConfig:
    cloudserver_url: str
    auth_token: str
    home_slug: str
    ssh: SSHConfig
    port_base: int
    port_count: int
    tcp_port_base: int | None = None
    tcp_port_count: int | None = None
    # Directory containing the config file; used to resolve relative paths.
    config_dir: Path = field(default_factory=Path.cwd)
    # Absolute path to the SQLite database file, resolved at load time.
    database: Path = field(default_factory=lambda: Path('db.sqlite3'))
    # Absolute path to this profile's certbot state dir (config/work/logs), resolved at load time.
    certbot_dir: Path = field(default_factory=lambda: Path('certbot'))
    certbot: CertbotConfig = field(default_factory=CertbotConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)


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
            path = Path(p).expanduser()
            return path if path.is_absolute() else (config_dir / path).resolve()

        db_path = resolve(data.get('database') or 'db.sqlite3')
        certbot_dir = resolve('certbot')

        raw_deploy = certbot_data.get('deploy_path')
        certbot_deploy = resolve(raw_deploy) if raw_deploy else None

        features_data = data.get('features') or {}
        features = FeaturesConfig(
            lan_forwarding=bool(features_data.get('lan_forwarding', False)),
        )

        tcp_ports = cl.get('tcp_ports') or {}
        ssh_data = dict(cl['ssh'])

        # Present-but-blank required fields (e.g. an unfilled dashboard download)
        # must fail the same way an absent field does, not silently proceed.
        if not cl.get('auth_token'):
            raise KeyError('auth_token')
        if not ssh_data.get('private_key_path'):
            raise KeyError('private_key_path')

        ssh_data['private_key_path'] = str(resolve(ssh_data['private_key_path']))

        return CloudConfig(
            cloudserver_url=cl['cloudserver_url'],
            auth_token=cl['auth_token'],
            home_slug=cl['home_slug'],
            ssh=SSHConfig(**ssh_data),
            port_base=cl['ports']['base'],
            port_count=cl['ports']['count'],
            tcp_port_base=tcp_ports.get('base'),
            tcp_port_count=tcp_ports.get('count'),
            config_dir=config_dir,
            database=db_path,
            certbot_dir=certbot_dir,
            certbot=CertbotConfig(deploy_path=certbot_deploy),
            features=features,
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f'config.yaml is missing required field: {e}') from e


_config: CloudConfig | None = None


def get_config() -> CloudConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
