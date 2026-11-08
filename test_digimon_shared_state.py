"""One four-seat snapshot serves every room size without changing its bytes."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from build_digimon import ARENA_REFERENCES
from build_don import RESERVE, SHARED_SIZE
from digimon_core import DigimonCore
from don_online import (cache_state_name, load_initial, make_package,
                        shared_profile_for, unpack_package)
from don_profiles import create_profile
from game_adapters import DIGIMON


class SharedDigimonStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profiles = self.root/'profiles'
        folder = self.profiles/'4p/common'
        folder.mkdir(parents=True)
        state = folder/DIGIMON.state_name
        base = DIGIMON.base+0x1000
        memory = bytearray(32*1024*1024)
        memory[DIGIMON.base:DIGIMON.base+8] = b'codecode'
        struct.pack_into('<16I', memory, base, DIGIMON.magic, 1, SHARED_SIZE,
                         1, 0, 1, 2, 0, 0, 1, 0, 15, 1, 4, 0, 0)
        for high, _, new_high, low, _, new_low in ARENA_REFERENCES:
            struct.pack_into('<I', memory, high, new_high)
            struct.pack_into('<I', memory, low, new_low)
        with zipfile.ZipFile(state, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('eeMemory.bin', memory)
        self.metadata = {'schema':1, 'adapter':DIGIMON.adapter, 'experimental':True,
            'online_verified':False, 'hash_kind':'inputs-only', 'source_serial':DIGIMON.serial,
            'source_crc':DIGIMON.crc, 'source_elf_sha256':DIGIMON.elf_sha256,
            'boot_crc':'12345678', 'boot_sha256':'b'*64, 'disc_sha256':'c'*64,
            'payload_base':DIGIMON.base, 'reserve_size':RESERVE, 'shared_base':base,
            'shared_size':SHARED_SIZE, 'code_size':8,
            'code_sha256':hashlib.sha256(b'codecode').hexdigest(), 'symbols':{},
            'arena_reservation':2, 'pad_layout':'port2'}
        create_profile(state, self.metadata, 4, 'PCSX2 v2.8.2', folder)

    def test_same_state_and_symbols_for_all_room_sizes(self):
        hashes, cache_names = set(), set()
        for count in (2, 3, 4):
            selected, manifest = shared_profile_for(self.profiles, count)
            self.assertEqual(manifest['pads'], DIGIMON.pads(count))
            package = make_package(selected, self.root/f'{count}.zip', manifest=manifest)
            state, _ = unpack_package(package, manifest, self.root/f'received-{count}')
            hashes.add(hashlib.sha256(state.read_bytes()).hexdigest())
            cache_names.add(cache_state_name(manifest))
        self.assertEqual(len(hashes), 1)
        self.assertEqual(len(cache_names), 1)
        # Deriving room manifests must preserve the captured four-seat manifest.
        self.assertEqual(len(json.loads(Path(selected['manifest']).read_text())['pads']), 4)

    def test_reconfigures_only_frozen_state_and_neutralizes_unused_sockets(self):
        for count in (2, 3, 4):
            core = object.__new__(DigimonCore)
            core.capacity = 4
            header = dict(active=1, abort=0, hold=1, frame=0, captures=1, players=4)
            core.get = header.__getitem__
            core.put = lambda key, value: header.__setitem__(key, value)
            core.publish = Mock()
            core.configure_players(count)
            self.assertEqual(header['players'], count)
            self.assertEqual(core.capacity, count)
            self.assertEqual({call.args[0] for call in core.publish.call_args_list}, set(range(count, 4)))
            self.assertTrue(all(set(call.args[1]) == set(range(11)) for call in core.publish.call_args_list))
            header['hold'] = 0
            with self.assertRaisesRegex(ValueError, 'congelado'):
                core.configure_players(count)

    def test_load_configures_room_size_after_loading_common_snapshot(self):
        for count in (2, 3, 4):
            selected, manifest = shared_profile_for(self.profiles, count)
            pine = Mock()
            pine.version.return_value = manifest['emulator']
            pine.game_id.return_value = DIGIMON.serial
            pine.game_crc.return_value = DIGIMON.crc
            pine.status.return_value = 0
            directory = self.root/f'sstates-{count}'
            directory.mkdir()
            previous, loaded = Mock(), Mock()
            previous.get.return_value = 0
            loaded.frozen.side_effect = lambda n: n == 4
            with patch('digimon_core.DigimonCore', side_effect=[previous, loaded]):
                result = load_initial(pine, self.metadata, manifest, selected['state'], directory)
            self.assertIs(result, loaded)
            loaded.configure_players.assert_called_once_with(count)


if __name__ == '__main__':
    unittest.main()
