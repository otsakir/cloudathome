import argparse
from io import StringIO
from unittest.mock import call, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from tunnels.models import Home, HomeBaseDomain
from tunnels.services import BaseDomainService, HAProxyService
from tunnels.ssh.manage_home import Config, TunnelManager, _build_parser
import os
import shutil
from argparse import ArgumentParser
from pathlib import Path


class ParserSeriousError(ValueError):
    pass


class WrapErrorParser(ArgumentParser):
    def error(self, message):
        raise ParserSeriousError(message)
    pass

class TunnelManagerTest(SimpleTestCase):

    def setUp(self):
        config = Config()

        fixtures_dir = os.path.join( os.path.dirname(__file__), 'fixtures')
        self.fixtures_dir = fixtures_dir

        shutil.copy(os.path.join(fixtures_dir, 'template', '01-allowed_users.conf'), os.path.join(fixtures_dir, 'sshd_config.d'))
        config.SSHD_CONFIGD_PATH = os.path.join(fixtures_dir, 'sshd_config.d')
        config.PUBLIC_KEY_STORAGE_PATH = os.path.join(fixtures_dir, 'public_keys')

        # copy a public key there to make sure it's found
        shutil.copy(os.path.join(self.fixtures_dir, 'template', 'authorized_keys'), os.path.join(self.fixtures_dir, 'public_keys', 'authorized_keys'))


        self.m = TunnelManager(config)
        self.parser = _build_parser(self.m, WrapErrorParser)

    def test_add_to_allow_users(self):
        self.assertTrue(self.m.add_username_to_allow_users('nick'))

    def test_remove_from_allow_users(self):
        self.assertTrue(self.m.remove_username_from_allow_users('tester'))

    def test_user_sshd_config(self):
        self.m.add_user_sshdconfig('nick', 3000)
        p = Path(os.path.join(self.fixtures_dir, 'sshd_config.d', 'nick.conf'))
        self.assertTrue(p.exists())
        # TODO check all ports are added accordingly

        self.m.remove_user_sshdconfig('nick')
        self.assertFalse(p.exists())



    # test argument parser

    def test_arg_parser_missing_public_key(self):
        with self.assertRaises(ParserSeriousError):
            self.parser.parse_args(['add', 'tester', '1', '-p', 'missing_public_key'])

    def test_arg_parser_home_id(self):
        args = self.parser.parse_args(['add', 'tester', '2', '-p', 'authorized_keys'])
        self.assertEqual(args.home_id, 2)

        with self.assertRaises(ValueError):
            self.parser.parse_args(['add', 'tester', 'asdf', '-p', 'authorized_keys'])

        with self.assertRaises(ValueError):
            self.parser.parse_args(['add', 'tester', '-5', '-p', 'authorized_keys'])

        with self.assertRaises(ValueError):
            self.parser.parse_args(['add', 'tester', '15', '-p', 'authorized_keys'])

    def test_arg_parser_username(self):
        with self.assertRaises(ParserSeriousError):
            self.parser.parse_args(['add', 'longusername01234567890123456789', '15', '-p', 'authorized_keys'])

        with self.assertRaises(ParserSeriousError):
            self.parser.parse_args(['add', 'otsakir#asdf', '15', '-p', 'authorized_keys'])


class HomeDestroyCascadeTest(TestCase):
    """Regression coverage for the slot-reuse leak: releasing a home must not leave
    base domains, live mappings, or a bandwidth limit behind for the next occupant."""

    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pw')
        self.token = Token.objects.create(user=self.user)
        # home_index 0 is already provisioned by migration 0003_provision_homes; claim it.
        self.home = Home.objects.get(home_index=0)
        self.home.user = self.user
        self.home.public_key = 'ssh-ed25519 AAAA...'
        self.home.slug = 'testslug'
        self.home.bandwidth_limit_kbps = 5000
        self.home.save()
        HomeBaseDomain.objects.create(home=self.home, domain='example.com')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    @patch('api.views.ElevatedOperations.remove_home_user')
    @patch('api.views.HAProxyService.remove_tcp_mapping')
    @patch('api.views.HAProxyService.remove_http_mapping')
    @patch('api.views.HAProxyService.get_home_mappings')
    def test_destroy_cascades_mappings_domains_and_bandwidth(
        self, mock_get_mappings, mock_remove_http, mock_remove_tcp, mock_remove_user,
    ):
        mock_get_mappings.return_value = [
            {'scheme': 'https', 'host': 'example.com', 'public_port': 443, 'tunnel_port': 2000},
            {'scheme': 'tcp', 'public_port': 10000, 'tunnel_port': 2001},
        ]

        resp = self.client.delete(f'/api/homes/{self.home.slug}/')

        self.assertEqual(resp.status_code, 204)
        mock_remove_http.assert_called_once_with('https', 'example.com', 443)
        mock_remove_tcp.assert_called_once_with(10000)
        mock_remove_user.assert_called_once()

        self.home.refresh_from_db()
        self.assertIsNone(self.home.user)
        self.assertIsNone(self.home.slug)
        self.assertIsNone(self.home.public_key)
        self.assertIsNone(self.home.bandwidth_limit_kbps)
        self.assertEqual(self.home.base_domains.count(), 0)

    @patch('api.views.ElevatedOperations.remove_home_user')
    @patch('api.views.HAProxyService.get_home_mappings', return_value=[])
    def test_destroy_twice_is_idempotent_not_500(self, mock_get_mappings, mock_remove_user):
        first = self.client.delete(f'/api/homes/{self.home.slug}/')
        self.assertEqual(first.status_code, 204)

        second = self.client.delete(f'/api/homes/{self.home.slug}/')
        self.assertEqual(second.status_code, 404)


class RevokeTokenViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='bob', password='pw')
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_revoke_deletes_token_and_old_token_then_401s(self):
        resp = self.client.delete('/api/auth/token/')
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Token.objects.filter(user=self.user).count(), 0)

        retry = self.client.get('/api/homes/')
        self.assertEqual(retry.status_code, 401)


class BaseDomainServiceAdminHostnameGuardTest(TestCase):
    """CAH_HOSTNAME (see settings.py) is reserved -- a home must not be able to
    register it, or a domain that overlaps it, as a base domain."""

    @override_settings(CAH_HOSTNAME='cloud.example.com')
    def test_exact_match_is_rejected(self):
        with self.assertRaises(ValueError):
            BaseDomainService.validate('cloud.example.com')

    @override_settings(CAH_HOSTNAME='cloud.example.com')
    def test_subdomain_of_admin_hostname_is_rejected(self):
        with self.assertRaises(ValueError):
            BaseDomainService.validate('sub.cloud.example.com')

    @override_settings(CAH_HOSTNAME='sub.cloud.example.com')
    def test_parent_of_admin_hostname_is_rejected(self):
        with self.assertRaises(ValueError):
            BaseDomainService.validate('cloud.example.com')

    @override_settings(CAH_HOSTNAME='cloud.example.com')
    def test_unrelated_domain_is_accepted(self):
        self.assertEqual(BaseDomainService.validate('myhome.example.com'), 'myhome.example.com')

    @override_settings(CAH_HOSTNAME=None)
    def test_no_admin_hostname_configured_imposes_no_restriction(self):
        self.assertEqual(BaseDomainService.validate('cloud.example.com'), 'cloud.example.com')


class BaseDomainServiceRegistrabilityTest(TestCase):
    """By default a base domain must be real and registrable (Public Suffix
    List, via tldextract). settings.BASE_DOMAIN_ALLOW_NON_REGISTRABLE relaxes
    only that check, for local/dev use -- everything else (CAH_HOSTNAME
    reservation, overlap between homes) still applies regardless."""

    def test_non_registrable_domain_rejected_by_default(self):
        with self.assertRaises(ValueError):
            BaseDomainService.validate('localhost')

    @override_settings(BASE_DOMAIN_ALLOW_NON_REGISTRABLE=True)
    def test_non_registrable_domain_accepted_when_relaxed(self):
        self.assertEqual(BaseDomainService.validate('localhost'), 'localhost')
        self.assertEqual(BaseDomainService.validate('myapp.local'), 'myapp.local')

    @override_settings(BASE_DOMAIN_ALLOW_NON_REGISTRABLE=True)
    def test_garbage_still_rejected_when_relaxed(self):
        with self.assertRaises(ValueError):
            BaseDomainService.validate('not a hostname!')

    @override_settings(BASE_DOMAIN_ALLOW_NON_REGISTRABLE=True, CAH_HOSTNAME='localhost')
    def test_admin_hostname_reservation_still_applies_when_relaxed(self):
        with self.assertRaises(ValueError):
            BaseDomainService.validate('localhost')


class EnsureAdminRouteTest(TestCase):
    """HAProxyService.ensure_admin_route (run at container start via
    manage.py reconcile_admin_route) seeds the static map entries when
    CAH_HOSTNAME is configured. Which backend the HTTP entry points to, and
    whether an HTTPS entry gets seeded at all, depends entirely on
    https_available() (cert/key file presence) -- no separate on/off
    setting."""

    @override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=80, CAH_HTTPS_PORT=443)
    @patch('tunnels.services.HAProxyService.https_available', return_value=True)
    @patch('tunnels.services.HAProxyService._send_command')
    def test_seeds_redirect_and_https_entries_when_cert_present(self, mock_send, mock_https_available):
        result = HAProxyService.ensure_admin_route()
        mock_send.assert_has_calls([
            call('del map /usr/local/etc/haproxy/maps/host_http_backends.map cloud.example.com:80'),
            call('add map /usr/local/etc/haproxy/maps/host_http_backends.map cloud.example.com:80 cah_django_http_redirect_backend'),
            call('del map /usr/local/etc/haproxy/maps/sni_backends.map cloud.example.com:443'),
            call('add map /usr/local/etc/haproxy/maps/sni_backends.map cloud.example.com:443 cah_django_https_backend'),
        ])
        self.assertEqual(mock_send.call_count, 4)
        self.assertEqual(result, {'https_enabled': True})

    @override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=80, CAH_HTTPS_PORT=443)
    @patch('tunnels.services.HAProxyService.https_available', return_value=False)
    @patch('tunnels.services.HAProxyService._send_command')
    def test_seeds_plain_http_entry_only_when_no_cert(self, mock_send, mock_https_available):
        result = HAProxyService.ensure_admin_route()
        mock_send.assert_has_calls([
            call('del map /usr/local/etc/haproxy/maps/host_http_backends.map cloud.example.com:80'),
            call('add map /usr/local/etc/haproxy/maps/host_http_backends.map cloud.example.com:80 cah_django_http_backend'),
            call('del map /usr/local/etc/haproxy/maps/sni_backends.map cloud.example.com:443'),
        ])
        self.assertEqual(mock_send.call_count, 3)
        self.assertEqual(result, {'https_enabled': False})

    @override_settings(CAH_HOSTNAME=None)
    @patch('tunnels.services.HAProxyService._send_command')
    def test_no_op_when_unconfigured(self, mock_send):
        result = HAProxyService.ensure_admin_route()
        mock_send.assert_not_called()
        self.assertIsNone(result)


class ReconcileAdminRouteCommandTest(TestCase):
    """The management command (run on every container start) refuses to start
    up at all without CAH_HOSTNAME -- it's the only way to reach Django now
    that CAH_API_PORT is gone -- and reports which of Django's HTTP/HTTPS
    entrypoints ended up enabled."""

    @override_settings(CAH_HOSTNAME=None)
    def test_raises_when_cah_hostname_unset(self):
        with self.assertRaises(CommandError):
            call_command('reconcile_admin_route')

    @override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=80, CAH_HTTPS_PORT=443)
    @patch('tunnels.services.HAProxyService.https_available', return_value=True)
    @patch('tunnels.services.HAProxyService._send_command')
    def test_reports_https_enabled_when_cert_present(self, mock_send, mock_https_available):
        out = StringIO()
        call_command('reconcile_admin_route', stdout=out)
        self.assertEqual(mock_send.call_count, 4)
        output = out.getvalue()
        self.assertIn('Django HTTP:  enabled at http://cloud.example.com/ (redirects to HTTPS)', output)
        self.assertIn('Django HTTPS: enabled at https://cloud.example.com/', output)

    @override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=80, CAH_HTTPS_PORT=443)
    @patch('tunnels.services.HAProxyService.https_available', return_value=False)
    @patch('tunnels.services.HAProxyService._send_command')
    def test_reports_https_disabled_when_no_cert(self, mock_send, mock_https_available):
        out = StringIO()
        call_command('reconcile_admin_route', stdout=out)
        self.assertEqual(mock_send.call_count, 3)
        output = out.getvalue()
        self.assertIn('Django HTTP:  enabled at http://cloud.example.com/', output)
        self.assertNotIn('redirects to HTTPS', output)
        self.assertIn('Django HTTPS: disabled -- no cert found at', output)
