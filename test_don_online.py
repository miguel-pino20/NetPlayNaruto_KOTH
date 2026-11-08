"""Package integrity, stock-PCXS2 loading, and explicit experimental activation."""
import hashlib
import io
import json
import queue
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from build_don import BASE, RESERVE, SHARED_SIZE
from don_adapter import CRC, ELF_SHA256
from discord_auth import AccountError
from don_online import (OnlineSession, _cleanup_loading_copy, load_initial, make_package,
                        manifest_for, state_request, unpack_package)
from don_profiles import create_profile
from multiplayer_client import RoomClient, DonRoomClient, make_node
import test_multiplayer as fixtures


class DonOnlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profiles = self.root/'profiles'
        self.profile = self.profiles/'2p/revision'
        self.profile.mkdir(parents=True)
        ram = bytearray(32*1024*1024)
        ram[BASE:BASE+8] = b'codecode'
        self.base = BASE+0x1000
        struct.pack_into('<16I', ram, self.base, 0x34504e44, 1, SHARED_SIZE, 1, 0, 1, 2, 0, 0, 1, 0, 15, 1, 2, 0, 0)
        state = self.profile/'DON-organicense.p2s'
        with zipfile.ZipFile(state, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('eeMemory.bin', ram)
        self.metadata = {'schema': 1, 'adapter': 'don-experimental-input-v1', 'experimental': True,
            'online_verified': False, 'hash_kind': 'inputs-only', 'source_serial': 'SLPS-25675',
            'source_crc': CRC, 'source_elf_sha256': ELF_SHA256, 'boot_crc': '12345678',
            'boot_sha256': 'b'*64, 'disc_sha256': 'c'*64, 'payload_base': BASE, 'reserve_size': RESERVE,
            'shared_base': self.base, 'shared_size': SHARED_SIZE, 'code_size': 8,
            'code_sha256': hashlib.sha256(b'codecode').hexdigest(), 'symbols': {}}
        create_profile(state, self.metadata, 2, 'PCSX2 v2.8.2', self.profile)
        self.selected, self.manifest = manifest_for(self.profiles, 2)
        self.package = make_package(self.selected, self.root/'initial.zip')

    def test_portable_package_loads_without_host_paths(self):
        state, metadata = unpack_package(self.package, self.manifest, self.root/'received')
        self.assertEqual(hashlib.sha256(state.read_bytes()).hexdigest(), self.manifest['state_sha256'])
        self.assertNotIn('boot_path', metadata)
        self.assertNotIn('disc_path', metadata)

    def test_tampering_wrong_manifest_and_extra_paths_fail(self):
        with self.assertRaisesRegex(ValueError, 'otra sala'):
            unpack_package(self.package, {**self.manifest, 'crc': 'DEADBEEF'}, self.root/'wrong')
        bad_symbols = self.root/'bad-symbols.zip'
        with zipfile.ZipFile(self.package) as original, zipfile.ZipFile(bad_symbols, 'w') as changed:
            for name in original.namelist():
                changed.writestr(name, b'{}' if name == 'symbols.json' else original.read(name))
        with self.assertRaisesRegex(ValueError, 'símbolos'):
            unpack_package(bad_symbols, self.manifest, self.root/'bad')
        # Rewrite both manifests so the actual state hash check is exercised.
        bad = self.root/'bad.zip'
        with zipfile.ZipFile(self.package) as original, zipfile.ZipFile(bad, 'w') as changed:
            for name in original.namelist():
                changed.writestr(name, b'changed state' if name == 'state.p2s' else original.read(name))
        with self.assertRaisesRegex(ValueError, 'estado descargado'):
            unpack_package(bad, self.manifest, self.root/'bad-state')
        with zipfile.ZipFile(self.package, 'a') as archive:
            archive.writestr('../escape', b'bad')
        with self.assertRaisesRegex(ValueError, 'formato'):
            unpack_package(self.package, self.manifest, self.root/'escape')

    def test_stock_pcsx2_load_is_validated_then_uses_free_slot_and_cleans_copy(self):
        pine = Mock()
        pine.version.return_value = self.manifest['emulator']
        pine.game_id.return_value = 'SLPS_256.75'
        pine.game_crc.return_value = CRC
        pine.status.return_value = 0
        directory = self.root/'sstates'
        directory.mkdir()
        existing = directory/'previous.09.p2s'
        existing.write_bytes(b'previous state')
        with patch('don_core.DonCore') as factory:
            factory.return_value.frozen.return_value = True
            load_initial(pine, self.metadata, self.manifest, self.selected['state'], directory)
        pine.load_state.assert_called_once_with(8)
        saved = directory/f"DON-inicial-2p-{self.manifest['state_sha256'][:16]}.p2s"
        self.assertEqual(set(directory.iterdir()), {existing, saved})
        self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), self.manifest['state_sha256'])
        self.assertEqual(existing.read_bytes(), b'previous state')

    def test_wrong_emulator_is_rejected_before_loading(self):
        pine = Mock()
        pine.version.return_value = 'other build'
        with self.assertRaisesRegex(ValueError, 'misma versión'):
            load_initial(pine, self.metadata, self.manifest, self.selected['state'], self.root)
        pine.load_state.assert_not_called()

    def test_windows_locked_loading_copy_does_not_abort_a_loaded_game(self):
        pine = Mock()
        pine.version.return_value = self.manifest['emulator']
        pine.game_id.return_value = 'SLPS-25675'
        pine.game_crc.return_value = CRC
        pine.status.return_value = 0
        directory = self.root/'windows-sstates'
        directory.mkdir()
        target = directory/f'SLPS-25675 ({CRC}).09.p2s'
        original_unlink = Path.unlink
        locked = PermissionError('File is still open in PCSX2')
        locked.winerror = 32
        def unlink(path, *args, **kwargs):
            if path == target:
                raise locked
            return original_unlink(path, *args, **kwargs)
        with patch('don_core.DonCore') as factory:
            factory.return_value.frozen.return_value = True
            with patch.object(Path, 'unlink', autospec=True, side_effect=unlink):
                core = load_initial(pine, self.metadata, self.manifest, self.selected['state'], directory)
            self.assertIs(core, factory.return_value)
            self.assertTrue(target.is_file())
            self.assertEqual(core.loading_copy, (target, self.manifest['state_sha256']))
            _cleanup_loading_copy(core)
            self.assertFalse(target.exists())
            self.assertIsNone(core.loading_copy)

    def test_cancel_before_start_has_no_api_or_pine_side_effects(self):
        client, events = Mock(), queue.Queue()
        session = OnlineSession(client, {'role': 'host'}, events)
        session.stop()
        session.run()
        client.create.assert_not_called()
        self.assertEqual(events.get_nowait()[0], 'done')

    def test_revoked_api_ticket_cancels_session_instead_of_continuing(self):
        client, events = Mock(), queue.Queue()
        client.request.side_effect = AccountError('Ticket revocado', 401)
        session = OnlineSession(client, {'role': 'guest', 'address': '10.147.0.2'}, events)
        session.room_id = '12345678-1234-1234-1234-123456789abc'
        session.heartbeat(self.manifest)
        self.assertTrue(session.cancel.is_set())
        self.assertEqual(session.api_error, 'Ticket revocado')

    def test_download_uses_ticket_fixed_route_full_hash_and_size(self):
        client = RoomClient('http://localhost:8000', 'test-ticket')
        data = self.package.read_bytes()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = [data, b'']
        with patch('don_online.urllib.request.urlopen', return_value=response) as opener:
            state_request(client, '12345678-1234-1234-1234-123456789abc', destination=self.root/'download.zip',
                          expected_sha=hashlib.sha256(data).hexdigest(), expected_size=len(data))
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-ticket')
        self.assertTrue(request.full_url.endswith('/12345678-1234-1234-1234-123456789abc/state/'))
        self.assertEqual((self.root/'download.zip').read_bytes(), data)

    def test_experimental_activation_is_explicit_and_don_only(self):
        snapshot = fixtures.MultiplayerClientTests().snapshot()
        core = fixtures.FourPadCore(0)
        core.simulation_hashes = False
        core.adapter_id = snapshot['manifest']['adapter'] = 'don-experimental-input-v1'
        with self.assertRaisesRegex(ValueError, 'estado del juego'):
            make_node(snapshot, core)
        with patch('multiplayer_client.Node') as factory:
            make_node(snapshot, core, experimental_don=True)
            self.assertTrue(factory.call_args.kwargs['generic'])
        snapshot['manifest']['game'] = 'un5'
        with self.assertRaises(ValueError):
            make_node(snapshot, core, experimental_don=True)

    def test_casual_account_client_never_enrolls_in_an_event(self):
        with patch('multiplayer_client.api_call', return_value={'ticket': 'casual-ticket', 'can_publish': False}) as api:
            client = DonRoomClient.authenticate('http://localhost:8000', 'launcher-session')
            self.assertEqual(api.call_args.args[2], '/api/netplay/don/access/')
            self.assertEqual(api.call_args.kwargs['extra_headers'], {'X-Netplay-Session': 'launcher-session'})
            client.create(None, 3)
            self.assertEqual(api.call_args.args[2:4], ('/api/netplay/don/sessions/', {'capacity': 3, 'delay': 3, 'network_protocol': 'don-bridge-v1'}))
            self.assertEqual(client.ticket, 'casual-ticket')
            self.assertFalse(any('/events/' in call.args[2] for call in api.call_args_list))

    def test_host_and_guest_download_state_without_iso_or_local_profiles(self):
        for role in ('host', 'guest'):
            events, client, pine, core = queue.Queue(), Mock(), Mock(), Mock()
            client.base_path = DonRoomClient.base_path
            room = {'id': '12345678-1234-1234-1234-123456789abc', 'manifest': self.manifest,
                    'package_sha256': hashlib.sha256(self.package.read_bytes()).hexdigest(),
                    'package_size': self.package.stat().st_size, 'status': 'lobby', 'session_epoch': 'epoch',
                    'network_protocol': 'don-bridge-v1'}
            client.create.return_value = client.request.return_value = room
            client.resolve_room.return_value = {'id': room['id']}
            pine.game_id.return_value, pine.status.return_value = 'SLPS-25675', 0
            config = {'role': role, 'room_id': room['id'], 'players': 2, 'pine_slot': 28011,
                      'state_dir': str(self.root), 'cache_dir': str(self.root)}
            session = OnlineSession(client, config, events)
            def sync(manifest, ready):
                session.snapshot = room
                if ready:
                    session.cancel.set()
                return room
            def download(*args, **kwargs):
                Path(kwargs['destination']).write_bytes(self.package.read_bytes())
            with patch('don_online.Pine') as factory, patch('don_online.state_request', side_effect=download) as transfer, \
                 patch('don_online.load_initial', return_value=core), patch.object(session, 'sync', side_effect=sync):
                factory.return_value.connect.return_value = pine
                session.run()
            errors = []
            while not events.empty():
                kind, value = events.get_nowait()
                if kind == 'error':
                    errors.append(value)
            self.assertEqual(errors, [], role)
            transfer.assert_called_once()
            self.assertNotIn('upload', transfer.call_args.kwargs)
            core.stop.assert_called_once()

    def test_standalone_player_ids_are_supported_without_participants(self):
        snapshot = fixtures.MultiplayerClientTests().snapshot()
        for player in snapshot['players']:
            player['player_id'] = player.pop('participant_id')
        with patch('multiplayer_client.Node') as factory:
            make_node(snapshot, fixtures.FourPadCore(0))
            self.assertEqual(factory.return_value.add_expected_peer.call_count, 3)


if __name__ == '__main__':
    unittest.main()
