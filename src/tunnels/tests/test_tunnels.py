import argparse
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from tunnels.models import Home, HomeBaseDomain
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
