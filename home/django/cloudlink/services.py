import requests
from .models import CloudConfig


class CloudServerError(Exception):
    pass


class CloudServerClient:
    def __init__(self, config: CloudConfig = None):
        self._config = config

    @property
    def config(self):
        if self._config is None:
            self._config = CloudConfig.get()
        return self._config

    def _headers(self):
        return {'Authorization': f'Token {self.config.auth_token}'}

    def _url(self, path):
        return f'{self.config.cloudserver_url.rstrip("/")}/{path.lstrip("/")}'

    def get_home(self):
        resp = requests.get(self._url('/api/homes/'), headers=self._headers())
        if resp.status_code != 200:
            raise CloudServerError(f'get_home failed: {resp.status_code} {resp.text}')
        homes = resp.json()
        if not homes:
            raise CloudServerError('no homes assigned to this account')
        return homes[0]

    def create_proxy_mapping(self, host, tunnel_port, scheme):
        resp = requests.post(
            self._url(f'/api/homes/{self.config.home_slug}/proxy-mappings/'),
            headers=self._headers(),
            json={'host': host, 'tunnel_port': tunnel_port, 'scheme': scheme},
        )
        if resp.status_code != 201:
            raise CloudServerError(f'create_proxy_mapping failed: {resp.status_code} {resp.text}')
        return resp.json()

    def delete_proxy_mapping(self, host):
        resp = requests.delete(
            self._url(f'/api/homes/{self.config.home_slug}/proxy-mappings/{host}/'),
            headers=self._headers(),
        )
        if resp.status_code != 204:
            raise CloudServerError(f'delete_proxy_mapping failed: {resp.status_code} {resp.text}')
