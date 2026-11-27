import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import launcher_core as core
import netlink
import netplay
import rooms
import statesync


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

    def test_zerotier_metadata_only_reveals_state_tag(self):
        server = statesync.StateServer(self.state, 0, bind='127.0.0.1', metadata_only=True)
        self.addCleanup(server.close)
        port = server.sock.getsockname()[1]
        self.assertEqual(statesync.advertised_tag('127.0.0.1', port), statesync.file_tag(self.state))
        dest = str(Path(self.folder.name) / 'should-not-download.p2s')
        with self.assertRaises(statesync.StateError):
            statesync.fetch('127.0.0.1', port, dest)
        self.assertFalse(Path(dest).exists())

    def test_host_and_guests_resolve_the_same_published_state_and_reuse_it(self):
        folder = Path(self.folder.name)
        state, symbols = folder / 'UN6-partida.p2s', folder / 'symbols_un6.json'
        symbols.write_bytes(b'{}')
        symbols_tag = core.state_tag(symbols)
        audio = b'audio at 20%'
        audio_tag = hashlib.sha256(audio).hexdigest()[:16]
        metadata = {'state': 'a' * 16, 'symbols': symbols_tag}
        backend = core.Backend()
        config = dict(game='un6', zerotier_state='audio20', zerotier_host='192.168.195.237',
                      symbols_path=str(symbols))

        def download(url, dest, tag):
            self.assertEqual(url, netlink.UN6_AUDIO20_STATE_URL)
            self.assertEqual(tag, audio_tag)
            dest.write_bytes(audio)

        with patch('launcher_core.game_paths', return_value=(state, symbols)), \
             patch('launcher_core.api_call', return_value=metadata) as defaults, \
             patch('launcher_core.UN6_AUDIO20_STATE_TAG', audio_tag), \
             patch('netlink.UN6_AUDIO20_STATE_TAG', audio_tag), \
             patch('launcher_core.UN6_PORTAL_SYMBOLS_TAG', symbols_tag), \
             patch('statesync.advertised_tag', return_value=audio_tag) as lookup, \
             patch.object(backend, '_download', side_effect=download) as downloads:
            for role, room_tag in (('host', None), ('guest', audio_tag), ('guest', None)):
                cfg = {**config, 'zerotier_state': 'audio20' if role == 'host' else 'standard'}
                backend.sync_zerotier_state(cfg, role, room_tag)
                event = backend.q.get(timeout=2)
                if event[0] == 'line':
                    event = backend.q.get(timeout=2)
                self.assertEqual(event[:2], ('sync', True), event)
                self.assertEqual(Path(cfg['state_file']).read_bytes(), audio)
                self.assertEqual(Path(cfg['symbols_path']), symbols)
            downloads.assert_called_once()
            defaults.assert_not_called()
            lookup.assert_called_once_with(config['zerotier_host'], 47400)
            self.assertFalse(state.exists())

    def test_koth_transformed_event_downloads_both_files_with_an_empty_cache(self):
        from koth_client import KOTH_STATES

        folder = Path(self.folder.name)
        state, symbols = folder / 'UN6-partida.p2s', folder / 'symbols_un6.json'
        game, variant = KOTH_STATES['un6-transformed']
        cfg = dict(game=game, zerotier_state=variant, symbols_path=str(symbols))
        backend = core.Backend()
        with patch('launcher_core.HERE', folder), patch('launcher_core.game_paths', return_value=(state, symbols)), \
                patch('launcher_core.api_call') as defaults, patch.object(backend, '_download') as download:
            # KOTH selects the event's files before Django assigns either player a role.
            backend.sync_zerotier_state(cfg, 'host')
            event = backend.q.get(timeout=2)
            while event[0] == 'line':
                event = backend.q.get(timeout=2)
            self.assertEqual(event, ('sync', True, ''))
            defaults.assert_not_called()
            self.assertEqual([call.args for call in download.call_args_list], [
                (netlink.UN6_PORTAL_STATE_URL, Path(cfg['state_file']), netlink.UN6_PORTAL_STATE_TAG),
                (f'{core.SERVER_URL}/blob/{netlink.UN6_PORTAL_SYMBOLS_TAG}',
                 Path(cfg['symbols_path']), netlink.UN6_PORTAL_SYMBOLS_TAG),
            ])

    def test_koth_audio20_uses_packaged_state_and_symbols_with_an_empty_cache(self):
        folder = Path(self.folder.name)
        state, symbols = folder / 'UN6-partida.p2s', folder / 'symbols_un6.json'
        cfg = dict(game='un6', zerotier_state='audio20', symbols_path=str(symbols))
        backend = core.Backend()
        with patch('launcher_core.game_paths', return_value=(state, symbols)), \
                patch('launcher_core.api_call') as defaults, patch.object(backend, '_download') as download:
            backend.sync_zerotier_state(cfg, 'host')
            self.assertEqual(backend.q.get(timeout=2), ('sync', True, ''))
            defaults.assert_not_called()
            download.assert_not_called()
        self.assertEqual(core.state_tag(cfg['state_file']), netlink.UN6_AUDIO20_STATE_TAG)
        self.assertEqual(core.state_tag(cfg['symbols_path']), netlink.UN6_PORTAL_SYMBOLS_TAG)

    def test_listed_zerotier_host_enables_discovery_for_its_game(self):
        self.cfg.update(announce_zerotier=True, game='un6')
        parsed = self.parse_command('host')
        self.assertEqual(parsed.announce_zerotier, 'un6')
        self.assertFalse(parsed.no_announce)
        self.assertTrue(parsed.no_share_state)
        packet = rooms.encode_room('Player', parsed.port, parsed.delay, 'a' * 16, game=parsed.announce_zerotier)
        self.assertEqual(rooms.parse_room(packet, (parsed.bind_address, 0))['game'], 'un6')
        legacy = rooms.encode_room('Player', parsed.port, parsed.delay, 'a' * 16)
        self.assertNotIn('game', rooms.parse_room(legacy, (parsed.bind_address, 0)))

    def test_zerotier_rooms_publish_guest_and_ping_only_while_playing(self):
        args = ('Host', 47400, 3, 'a' * 16)
        source = ('192.168.195.14', 0)
        data = rooms.encode_room(*args, 'playing', 'un6', guest='Invitado', ping=130)
        result = rooms.parse_room(data, source)
        self.assertEqual(result['players']['guest']['nick'], 'Invitado')
        self.assertEqual(result['ping'], 130)
        waiting = rooms.parse_room(rooms.encode_room(*args, game='un6', guest='Invitado', ping=130), source)
        self.assertNotIn('players', waiting)
        self.assertNotIn('ping', waiting)

    def test_zerotier_uses_directed_broadcast_only_on_selected_network(self):
        choices = [{'address': '10.2.3.4', 'prefix': 16}, {'address': '192.168.195.14', 'prefix': 24}]
        with patch('zerotier_networks.discover', return_value=(choices, '')), patch('rooms.uses_interface') as route:
            route.return_value = True
            self.assertEqual(rooms.zerotier_targets('10.2.3.4'), [rooms.ZEROTIER_GROUP, '10.2.255.255'])
            route.assert_called_once_with('10.2.255.255', '10.2.3.4')
            route.return_value = False
            self.assertEqual(rooms.zerotier_targets('10.2.3.4'), [rooms.ZEROTIER_GROUP])

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

    def test_un6_installs_the_selected_state_in_its_slot_without_saving_first(self):
        args = SimpleNamespace(state=str(self.state), state_dir=self.folder.name, load_slot=9,
                               pine_slot=28011, symbols='symbols_un6.json')
        with patch('netplay.Pine') as pine_class, patch('netplay.time.sleep'), \
             patch('netplay.core_link.resolve_base', return_value=(0, 0, {})), \
             patch('netplay.core_link.PineCore') as pine_core:
            pine = pine_class.return_value.connect.return_value
            pine.game_id.return_value = 'SLUS-55606'
            pine.game_crc.return_value = '688C83D6'
            pine_core.return_value.frozen.return_value = True
            for tag, slot in ((netlink.UN6_ORIGINAL_STATE_TAG, 9), (netlink.UN6_PORTAL_STATE_TAG, 8),
                              (netlink.UN6_AUDIO20_STATE_TAG, 7)):
                with self.subTest(slot=slot), patch('netplay.state_tag', return_value=tag):
                    self.assertTrue(netplay.load_match_state(args))
                    target = Path(self.folder.name) / f'SLUS-55606 (688C83D6).{slot:02d}.p2s'
                    self.assertEqual(target.read_bytes(), self.state.read_bytes())
                    pine.load_state.assert_called_with(slot)
            pine.save_state.assert_not_called()

    def test_un6_shared_state_and_relay_default_are_resolved_by_transport(self):
        api = 'https://example.test'
        metadata = {'state': netlink.UN6_ORIGINAL_STATE_TAG, 'symbols': netlink.UN6_PORTAL_SYMBOLS_TAG}
        audio = netlink.UN6_AUDIO20_STATE_URL, netlink.UN6_AUDIO20_STATE_TAG
        self.assertEqual(netlink.default_file(api, 'un6', 'state', metadata), audio)
        self.assertEqual(netlink.default_file(api, 'un6', 'state', metadata, relay=True),
                         (api + '/default/state?game=un6', netlink.UN6_ORIGINAL_STATE_TAG))
        self.assertEqual(netlink.default_file(api, 'un5', 'state', metadata),
                         (api + '/default/state', netlink.UN6_ORIGINAL_STATE_TAG))
        metadata['state'] = netlink.UN6_AUDIO20_STATE_TAG
        self.assertEqual(netlink.default_file(api, 'un6', 'state', metadata, relay=True), audio)



class NarutoRoomListingTests(unittest.TestCase):
    def test_room_listing_keeps_naruto_and_legacy_rooms_only(self):
        from types import SimpleNamespace
        backend = core.Backend.__new__(core.Backend)
        backend._online_busy = False
        backend._online_at = 0
        data = {'rooms': [{'id': 'un5', 'game': 'un5'}, {'id': 'un6', 'game': 'un6'},
                          {'id': 'legacy'}, {'id': 'other', 'game': 'unsupported'}, None]}
        with patch('launcher_core.api_call', return_value=data), \
                patch('launcher_core.threading.Thread', side_effect=lambda target, daemon: SimpleNamespace(start=target)):
            backend.poll_rooms()
        self.assertEqual([r['id'] for r in backend.online_rooms], ['un5', 'un6', 'legacy'])
        self.assertEqual(backend.online_error, '')
        self.assertFalse(backend._online_busy)
