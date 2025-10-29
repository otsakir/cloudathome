import argparse

from django.test import SimpleTestCase
from external.tunnels.manage_tunnel import Config, TunnelManager
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
        self.parser = self.m.get_parser(WrapErrorParser)

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
        # sudo python manage_tunnel.py add alice3 1 -p alice_public_key
        # sudo python manage_tunnel.py remove alice4 1
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

