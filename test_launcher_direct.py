import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher_core as core
import netplay


class DirectLauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.state = Path(self.folder.name) / 'match.p2s'
        self.state.write_bytes(b'match state')
        self.cfg = {**core.FIXED, 'transport': 'zerotier', 'zerotier_address': '192.168.195.14',
                    'zerotier_host': '192.168.195.237', 'state_dir': self.folder.name,
                    'nick': 'Player', 'ignore_desync': False}

    def parse_command(self, role):
        args = core.make_args(self.cfg, role, self.state)
        with patch('netplay.cmd_play', return_value=0) as play:
            netplay.main(args)
        parsed, is_host = play.call_args.args
        self.assertEqual(parsed.server, '')
        self.assertEqual(parsed.bind_address, self.cfg['zerotier_address'])
        self.assertEqual(parsed.delay, 3)
        self.assertEqual(is_host, role == 'host')
        return parsed

    def test_host_command_is_accepted_and_uses_direct_socket_without_room_services(self):
        parsed = self.parse_command('host')
        self.assertEqual(parsed.port, 47400)
        self.assertTrue(parsed.no_announce)
        self.assertTrue(parsed.no_share_state)

    def test_guest_command_connects_directly_without_online_room_or_state_fetch(self):
        parsed = self.parse_command('guest')
        self.assertEqual(parsed.connect, '192.168.195.237:47400')
        self.assertEqual(parsed.bind_port, 0)
        self.assertFalse(parsed.fetch_state)

    def test_bad_addresses_are_rejected_before_start(self):
        for address in ('', '0.0.0.0', '127.0.0.1', '::1', '224.0.0.1', '255.255.255.255', 'hostname'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                core.zerotier_args({**self.cfg, 'zerotier_address': address}, 'host')
        with self.assertRaises(ValueError):
            core.zerotier_args({**self.cfg, 'zerotier_host': self.cfg['zerotier_address']}, 'guest')

    def test_normal_online_mode_retains_principal_server(self):
        for role in ('host', 'guest'):
            cfg = {**self.cfg, 'transport': 'online', 'room_id': 'principal-room'}
            args = core.make_args(cfg, role, self.state)
            self.assertEqual(args[args.index('--server')+1], core.SERVER_ADDR)
            self.assertNotIn('--bind-address', args)

