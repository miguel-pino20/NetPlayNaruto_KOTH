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

    def test_zerotier_host_accepts_short_or_full_address(self):
        from mobile.backend import resolve_zerotier_host

        self.assertEqual(resolve_zerotier_host('172', '192.168.195.24'), '192.168.195.172')
        self.assertEqual(resolve_zerotier_host('10.147.0.12', '192.168.195.24'), '10.147.0.12')
        for value, local in (('172', ''), ('256', '192.168.195.24'), ('172', 'bad')):
            with self.subTest(value=value, local=local), self.assertRaises(ValueError):
                resolve_zerotier_host(value, local)

    def test_mobile_zerotier_guest_accepts_confirmed_django_room(self):
        from mobile.backend import discover_zerotier_rooms
        from rooms import ZEROTIER_GAME_PORT

        room = {'ip': '192.168.195.14', 'port': ZEROTIER_GAME_PORT, 'game': 'un6', 'status': 'waiting'}
        with (patch('rooms.RoomListener') as listener,
              patch('rooms.django_rooms', return_value=[room]) as lookup,
              patch('rooms.uses_interface', return_value=True)):
            listener.return_value.error = 'Multicast unavailable'
            listener.return_value.poll.return_value = []
            self.assertEqual(discover_zerotier_rooms('192.168.195.176', 'session'), [room])
        self.assertEqual(lookup.call_args.args[1:], ('session', '192.168.195.176', ZEROTIER_GAME_PORT))

    def test_event_categories_exclude_finished_events(self):
        from mobile.backend import active_events

        events = [{'status': 'draft', 'casual': True}, {'status': 'running', 'casual': False},
                  {'status': 'finished', 'casual': True}, {'status': 'finished'}]
        self.assertEqual(active_events(events, casual=True), [events[0]])
        self.assertEqual(active_events(events, casual=False), [events[1]])

    def test_event_match_prefers_configured_game_and_variant(self):
        from mobile.backend import event_match

        event = {'match_state': 'un6-transformed'}
        self.assertEqual(event_match({}, 'un5', event=event), ('un6', 'transformed'))
        self.assertEqual(event_match({'match_state': 'un6-audio20'}, 'un5', event=event), ('un6', 'audio20'))
        self.assertEqual(event_match({}, 'un5'), ('un5', None))
        with self.assertRaises(ValueError):
            event_match({'match_state': 'unsupported'}, 'un5')

    def test_appearance_collection_contains_only_owned_items(self):
        from mobile.backend import owned_appearance

        owned = {'id': 1, 'name': 'Shikamaru', 'owned': True, 'price': 2, 'image_version': 'a' * 64}
        unclaimed = dict(owned, id=2, owned=False, price=0)
        with patch('discord_auth.api_call', return_value={'items': [owned, unclaimed]}) as api:
            collection = owned_appearance('session')
        self.assertEqual(collection['background'], {'1': owned})
        self.assertEqual(collection['character'], {'1': owned})
        self.assertEqual([call.args[2] for call in api.call_args_list],
                         ['/api/netplay/store/backgrounds/', '/api/netplay/store/characters/'])
        self.assertTrue(all(call.kwargs['extra_headers'] == {'X-Netplay-Session': 'session'}
                            and call.kwargs['follow_redirects'] is False for call in api.call_args_list))

    def test_mobile_store_purchase_sends_the_displayed_price(self):
        from mobile.backend import appearance_store

        with patch('discord_auth.api_call', return_value={'balance': 7}) as api:
            self.assertEqual(appearance_store('session', 'character', item={'id': 4, 'price': 3}), {'balance': 7})
        self.assertEqual(api.call_args.args[1:], ('POST', '/api/netplay/store/characters/4/purchase/', {'price': 3}))

    def test_history_portraits_deduplicate_and_allow_only_character_paths(self):
        from mobile.backend import history_portraits

        path = '/static/characters/42.ab12.png'
        fights = [{'players': [{'portrait': path}, {'portrait': path},
                               {'portrait': 'https://example.com/42.png'}, {'portrait': None}]}]
        with patch('mobile.backend._history_portrait', return_value='portrait.png') as fetch:
            self.assertEqual(history_portraits('/cache', fights), {path: 'portrait.png'})
        fetch.assert_called_once_with('/cache', path)

class MobileHostTests(unittest.TestCase):
    def test_armsx2_slots_follow_un6_variants(self):
        from mobile.host import emulator_slot
        from netlink import UN6_AUDIO20_STATE_TAG, UN6_ORIGINAL_STATE_TAG, UN6_PORTAL_STATE_TAG

        self.assertEqual(emulator_slot('un5', None), 1)
        self.assertEqual(emulator_slot('un6', UN6_ORIGINAL_STATE_TAG), 1)
        self.assertEqual(emulator_slot('un6', UN6_PORTAL_STATE_TAG), 2)
        self.assertEqual(emulator_slot('un6', UN6_AUDIO20_STATE_TAG), 3)

    def test_zerotier_guest_matches_the_host_state(self):
        from mobile.host import zerotier_guest_state
        from netlink import UN6_AUDIO20_STATE_TAG, UN6_ORIGINAL_STATE_TAG
        from statesync import StateError

        with patch('statesync.advertised_tag', return_value=UN6_ORIGINAL_STATE_TAG) as query:
            self.assertEqual(zerotier_guest_state('un6', '192.168.195.14'), ('original', UN6_ORIGINAL_STATE_TAG))
            self.assertEqual(zerotier_guest_state('un6', '192.168.195.14', UN6_AUDIO20_STATE_TAG),
                             ('audio20', UN6_AUDIO20_STATE_TAG))
            query.assert_called_once_with('192.168.195.14', 47400)
        with patch('statesync.advertised_tag', side_effect=StateError('no announcement')):
            self.assertEqual(zerotier_guest_state('un6', '192.168.195.14'), (None, None))

    def test_mobile_zerotier_room_is_announced_without_disabling_state_sharing(self):
        from mobile.host import host_arguments
        from netplay import main

        command = host_arguments({'directory': '/private/mobile', 'game': 'un6', 'pine_slot': 28011,
                                  'address': '10.147.0.12', 'stop_file': '/private/mobile/host.stop',
                                  'transport': 'direct', 'announce_zerotier': True})
        with patch('netplay.cmd_play') as play:
            main(command)
        args = play.call_args.args[0]
        self.assertEqual(args.announce_zerotier, 'un6')
        self.assertTrue(args.share_zerotier_state)
        self.assertFalse(args.no_announce)

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
