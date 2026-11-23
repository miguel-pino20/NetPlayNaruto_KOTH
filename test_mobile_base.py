"""Verify mobile PINE wire compatibility against an actual loopback socket."""
import socket
import struct
import threading
import unittest
from unittest.mock import patch

from pine import Pine, PineError
from mobile.backend import pine_diagnostics, validate_address, https_url


class MobileBaseTests(unittest.TestCase):
    def test_tcp_connect_timeout_is_distinct_from_a_pine_reply_timeout(self):
        with patch('pine.socket.create_connection', side_effect=socket.timeout('timed out')) as connect:
            client = Pine(transport='tcp', timeout=3)
            with self.assertRaisesRegex(PineError, 'todavía no se envió ningún comando PINE'):
                client.connect()
            connect.assert_called_once_with(('127.0.0.1', 28011), timeout=3)
            self.assertIsNone(client.sock)

    def test_android_diagnostics_use_existing_pine_protocol_without_writes(self):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        port = server.getsockname()[1]
        commands, errors = [], []

        def receive(connection, count):
            data = b''
            while len(data) < count:
                part = connection.recv(count - len(data))
                if not part:
                    raise EOFError('Incomplete request')
                data += part
            return data

        def serve():
            try:
                with server, server.accept()[0] as connection:
                    connection.settimeout(3)
                    for text in (None, b'SLES-55605\0', b'C071D4C1\0', b'ARMSX2 test\0'):
                        size = struct.unpack('<I', receive(connection, 4))[0]
                        command = receive(connection, size - 4)
                        commands.append(command)
                        payload = struct.pack('<I', 0) if text is None else struct.pack('<I', len(text)) + text
                        reply = struct.pack('<I', len(payload) + 5) + b'\0' + payload
                        # Fragment replies to exercise TCP framing, not mock method calls.
                        connection.sendall(reply[:3])
                        connection.sendall(reply[3:])
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = pine_diagnostics(port)
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(commands, [b'\x0f', b'\x0c', b'\x0d', b'\x08'])
        self.assertIn('SLES-55605', result)
        self.assertIn('ARMSX2 test', result)

    def test_android_default_transport(self):
        with patch('pine.sys.getandroidapilevel', return_value=26, create=True):
            self.assertEqual(Pine().transport, 'tcp')

    def test_credentials_require_https_and_valid_base(self):
        for url in ('http://example.com', 'https://user:password@example.com', 'https://example.com/?token=x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                https_url(url)
        self.assertEqual(https_url('https://events.example.com/'), 'https://events.example.com')

    def test_reject_non_peer_addresses(self):
        for address in ('127.0.0.1', '0.0.0.0', '224.0.0.1', '169.254.1.2', 'bad'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                validate_address(address)
        self.assertEqual(validate_address('10.147.0.12'), '10.147.0.12')

class MobileHostTests(unittest.TestCase):
    def test_tournament_roles_use_the_shared_fixture_connection(self):
        from mobile.host import session_arguments
        from netplay import main

        for role in ('host', 'guest'):
            with self.subTest(role=role), patch('netplay.cmd_play') as play:
                command = session_arguments({
                    'directory': '/private/mobile', 'game': 'un6', 'pine_slot': 28011,
                    'address': '10.147.0.12', 'stop_file': '/private/mobile/host.stop',
                    'role': role, 'url': 'https://events.example.com',
                    'fixture': {'event_id': 7, 'fixture_id': 42},
                })
                main(command)
                args, is_host = play.call_args.args
                self.assertEqual(is_host, role == 'host')
                self.assertEqual(args.tournament_fixture, [7, 42])
                self.assertEqual(args.fixture_game, 'un6')
                self.assertEqual(args.api_url, 'https://events.example.com')
                self.assertEqual(args.bind_address, '10.147.0.12')
                self.assertFalse(args.server)
                self.assertTrue(args.auto_delay)
                self.assertNotIn('--connect', command)

    def test_host_reuses_desktop_protocol_options_without_relay(self):
        from mobile.host import host_arguments
        args = host_arguments({'directory': '/private/mobile', 'game': 'un6', 'pine_slot': 28011,
                               'address': '10.147.0.12', 'stop_file': '/private/mobile/host.stop', 'nick': 'P1'})
        self.assertIn('host', args)
        self.assertEqual(args[args.index('--port') + 1], '47400')
        self.assertEqual(args[args.index('--delay') + 1], '3')
        self.assertEqual(args[args.index('--bind-address') + 1], '10.147.0.12')
        self.assertEqual(args[args.index('--server') + 1], '')
        self.assertNotIn('--load-slot', args)  # No desktop filesystem copying on Android.

    def test_server_mode_uses_main_relay_and_ignores_zerotier_binding(self):
        from mobile.host import host_arguments
        from netlink import DEFAULT_SERVER, DEFAULT_API_URL
        args = host_arguments({'directory': '/private/mobile', 'game': 'un6', 'pine_slot': 28011,
                               'address': 'unused', 'stop_file': '/private/mobile/host.stop',
                               'transport': 'server', 'nick': 'Android P1'})
        self.assertEqual(args[args.index('--server') + 1], DEFAULT_SERVER)
        self.assertEqual(args[args.index('--api-url') + 1], DEFAULT_API_URL)
        self.assertIn('--relay-only', args)
        self.assertNotIn('--bind-address', args)
        self.assertEqual(args[args.index('--room-file') + 1], '/private/mobile/host-room.json')

    def test_host_rejects_invalid_game_before_accessing_emulator(self):
        from mobile.host import paths
        with self.assertRaises(ValueError):
            paths('/private/mobile', 'don')

    def test_host_does_not_open_socket_without_shared_files(self):
        import tempfile
        from mobile.host import run_host
        with tempfile.TemporaryDirectory() as directory:
            config = {'directory': directory, 'game': 'un6', 'pine_slot': 28011,
                      'address': '', 'stop_file': directory + '/host.stop'}
            with patch('pine.socket.create_connection') as connect:
                with self.assertRaisesRegex(ValueError, 'archivos compartidos'):
                    run_host(config, lambda *_: None)
                connect.assert_not_called()


class ControllerAndGuestTests(unittest.TestCase):
    def test_disconnected_second_port_is_enabled_without_changing_bindings(self):
        from mobile.host import ensure_controllers
        from unittest.mock import MagicMock
        client = MagicMock()
        client.armsx2_get_setting.side_effect = ['DualShock2', 'None']
        self.assertEqual(ensure_controllers(client), ['Pad2'])
        client.armsx2_set_setting.assert_called_once_with('Pad2', 'Type', 'DualShock2')

    def test_existing_controllers_are_not_reconfigured(self):
        from mobile.host import ensure_controllers
        from unittest.mock import MagicMock
        client = MagicMock()
        client.armsx2_get_setting.return_value = 'DualShock2'
        self.assertEqual(ensure_controllers(client), [])
        client.armsx2_set_setting.assert_not_called()

    def test_guest_has_its_own_peer_and_no_host_listen_port(self):
        from mobile.host import client_arguments
        args = client_arguments({'directory': '/private/mobile', 'game': 'un6', 'pine_slot': 28011,
                                 'address': '', 'stop_file': '/private/mobile/host.stop',
                                 'transport': 'direct', 'host_ip': '192.168.195.14'})
        self.assertIn('guest', args)
        self.assertNotIn('--port', args)
        self.assertEqual(args[args.index('--connect') + 1], '192.168.195.14:47400')
        self.assertEqual(args[args.index('--bind-port') + 1], '0')

    def test_server_guest_requires_real_room(self):
        from mobile.host import client_arguments
        config = {'directory': '/private/mobile', 'game': 'un6', 'pine_slot': 28011,
                  'address': '', 'stop_file': '/private/mobile/host.stop', 'transport': 'server'}
        with self.assertRaisesRegex(ValueError, 'sala válida'):
            client_arguments(config)
        args = client_arguments(dict(config, room_id='abc123'))
        self.assertEqual(args[args.index('--room') + 1], 'abc123')
        self.assertNotIn('--room-file', args)
        self.assertIn('--relay-only', args)

    def test_settings_reply_rejects_malformed_length(self):
        with self.assertRaises(PineError):
            Pine._setting_reply(b'\xff\xff\xff\xffx')
        with self.assertRaises(PineError):
            Pine._setting_reply(b'\x01\0\0\0x')
        self.assertEqual(Pine._setting_reply(b'\x05\0\0\0None\0'), 'None')


if __name__ == '__main__':
    unittest.main()
