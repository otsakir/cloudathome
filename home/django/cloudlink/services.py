import requests

from cloudlink.config import get_config


class CloudServerError(Exception):
    pass


class CloudServerClient:

    def _headers(self):
        return {'Authorization': f'Token {get_config().auth_token}'}

    def _url(self, path):
        return f'{get_config().cloudserver_url.rstrip("/")}/{path.lstrip("/")}'

    def get_home(self):
        resp = requests.get(self._url('/api/homes/'), headers=self._headers())
        if resp.status_code != 200:
            raise CloudServerError(f'get_home failed: {resp.status_code} {resp.text}')
        homes = resp.json()
        if not homes:
            raise CloudServerError('no homes assigned to this account')
        return homes[0]

    def create_proxy_mapping(self, scheme, host=None, public_port=None):
        if scheme == 'tcp':
            payload = {'scheme': 'tcp', 'public_port': public_port}
        else:
            payload = {'host': host, 'scheme': scheme}
        resp = requests.post(
            self._url(f'/api/homes/{get_config().home_slug}/proxy-mappings/'),
            headers=self._headers(),
            json=payload,
        )
        if resp.status_code != 201:
            raise CloudServerError(f'create_proxy_mapping failed: {resp.status_code} {resp.text}')
        return resp.json()

    def delete_proxy_mapping(self, key):
        resp = requests.delete(
            self._url(f'/api/homes/{get_config().home_slug}/proxy-mappings/{key}/'),
            headers=self._headers(),
        )
        if resp.status_code != 204:
            raise CloudServerError(f'delete_proxy_mapping failed: {resp.status_code} {resp.text}')

    def update_bandwidth(self, kbps_or_none):
        resp = requests.patch(
            self._url(f'/api/homes/{get_config().home_slug}/'),
            headers=self._headers(),
            json={'bandwidth_limit_kbps': kbps_or_none},
        )
        if resp.status_code != 200:
            raise CloudServerError(f'update_bandwidth failed: {resp.status_code} {resp.text}')
        return resp.json()
