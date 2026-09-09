from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from tunnels.models import Home, HomeBaseDomain


class InboundPortRangeViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pw')
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_http_range(self):
        resp = self.client.get('/api/config/inbound-ports/http/')
        self.assertEqual(resp.status_code, 200)
        base, count = settings.HTTP_INBOUND_PORT_RANGE
        self.assertEqual(resp.json(), {'scheme': 'http', 'ranges': [{'port_base': base, 'port_count': count}]})

    def test_https_range(self):
        resp = self.client.get('/api/config/inbound-ports/https/')
        self.assertEqual(resp.status_code, 200)
        base, count = settings.HTTPS_INBOUND_PORT_RANGE
        self.assertEqual(resp.json(), {'scheme': 'https', 'ranges': [{'port_base': base, 'port_count': count}]})

    def test_unknown_scheme_404s(self):
        resp = self.client.get('/api/config/inbound-ports/tcp/')
        self.assertEqual(resp.status_code, 404)

    def test_requires_authentication(self):
        anon = APIClient()
        resp = anon.get('/api/config/inbound-ports/https/')
        self.assertEqual(resp.status_code, 401)


class SchemeProxyMappingPortTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='bob', password='pw')
        self.token = Token.objects.create(user=self.user)
        # home_index 0 is already provisioned by migration 0003_provision_homes; claim it.
        self.home = Home.objects.get(home_index=0)
        self.home.user = self.user
        self.home.public_key = 'ssh-ed25519 AAAA...'
        self.home.slug = 'testslug'
        self.home.save()
        HomeBaseDomain.objects.create(home=self.home, domain='example.com')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    @patch('api.views.HAProxyService.add_mapping')
    @patch('api.views.HAProxyService.get_used_ports', return_value=set())
    @patch('api.views.HAProxyService.mapping_exists', return_value=False)
    def test_create_without_public_port_defaults_to_scheme_standard_port(
        self, mock_exists, mock_used_ports, mock_add_mapping,
    ):
        resp = self.client.post('/api/homes/testslug/proxy-mappings/https/', {'host': 'example.com'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['public_port'], 443)
        mock_add_mapping.assert_called_once_with('https', 2000, host='example.com', public_port=443)

    @patch('api.views.HAProxyService.add_mapping')
    @patch('api.views.HAProxyService.get_used_ports', return_value=set())
    @patch('api.views.HAProxyService.mapping_exists', return_value=False)
    def test_create_with_public_port_in_range(self, mock_exists, mock_used_ports, mock_add_mapping):
        base, _ = settings.HTTPS_INBOUND_PORT_RANGE
        resp = self.client.post(
            '/api/homes/testslug/proxy-mappings/https/', {'host': 'example.com', 'public_port': base},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['public_port'], base)
        mock_add_mapping.assert_called_once_with('https', 2000, host='example.com', public_port=base)

    @patch('api.views.HAProxyService.get_used_ports', return_value=set())
    @patch('api.views.HAProxyService.mapping_exists', return_value=False)
    def test_create_with_public_port_outside_range_is_rejected(self, mock_exists, mock_used_ports):
        resp = self.client.post(
            '/api/homes/testslug/proxy-mappings/https/', {'host': 'example.com', 'public_port': 1},
        )
        self.assertEqual(resp.status_code, 400)

    @patch('api.views.HAProxyService.mapping_exists', return_value=True)
    def test_create_conflicts_only_on_exact_host_scheme_port_repeat(self, mock_exists):
        resp = self.client.post('/api/homes/testslug/proxy-mappings/https/', {'host': 'example.com'})
        self.assertEqual(resp.status_code, 409)
        mock_exists.assert_called_once_with('https', 'example.com', 443)

    @patch('api.views.HAProxyService.remove_http_mapping')
    @patch('api.views.HAProxyService.mapping_exists', return_value=True)
    def test_delete_removes_the_mapping_at_the_given_port(self, mock_exists, mock_remove):
        resp = self.client.delete('/api/homes/testslug/proxy-mappings/https/example.com/8443/')
        self.assertEqual(resp.status_code, 204)
        mock_exists.assert_called_once_with('https', 'example.com', 8443)
        mock_remove.assert_called_once_with('https', 'example.com', 8443)

    @patch('api.views.HAProxyService.mapping_exists', return_value=False)
    def test_delete_with_no_active_mapping_at_that_port_404s(self, mock_exists):
        resp = self.client.delete('/api/homes/testslug/proxy-mappings/https/example.com/8443/')
        self.assertEqual(resp.status_code, 404)

    @patch('api.views.HAProxyService.add_mapping')
    @patch('api.views.HAProxyService.get_used_ports', return_value=set())
    @patch('api.views.HAProxyService.mapping_exists', return_value=False)
    def test_same_host_can_have_a_second_mapping_at_a_different_port(
        self, mock_exists, mock_used_ports, mock_add_mapping,
    ):
        """The same hostname can have independent https mappings at two
        different ports simultaneously -- http_frontend/https_frontend key
        their backend lookup on host:dst_port, not host alone (see
        haproxy.cfg), so only an exact (host, scheme, port) repeat conflicts."""
        base, _ = settings.HTTPS_INBOUND_PORT_RANGE
        resp = self.client.post(
            '/api/homes/testslug/proxy-mappings/https/', {'host': 'example.com', 'public_port': base},
        )
        self.assertEqual(resp.status_code, 201)
        mock_exists.assert_called_once_with('https', 'example.com', base)
