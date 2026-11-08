import hashlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from build_don import BASE, RESERVE, SHARED_SIZE
from don_adapter import ELF_SHA256
from don_core import prepare_state
from don_profiles import create_profile, select_profile, index_profiles


class DonProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.memory = bytearray(32*1024*1024)
        self.base = BASE+0x1000
        self.memory[BASE:BASE+8] = b'codecode'
        header = [0x34504e44, 1, SHARED_SIZE, 1, 0, 1, 2, 0, 0, 1, 0, 15, 1, 4, 0, 0]
        struct.pack_into('<16I', self.memory, self.base, *header)
        self.meta = {'schema': 1, 'adapter': 'don-experimental-input-v1', 'experimental': True,
                     'online_verified': False, 'hash_kind': 'inputs-only', 'source_serial': 'SLPS-25675',
                     'source_crc': '82EA02B7', 'source_elf_sha256': ELF_SHA256, 'boot_crc': '12345678',
                     'boot_sha256': 'b'*64, 'disc_sha256': 'c'*64,
                     'payload_base': BASE, 'reserve_size': RESERVE, 'shared_base': self.base,
                     'shared_size': SHARED_SIZE, 'code_size': 8,
                     'code_sha256': hashlib.sha256(b'codecode').hexdigest(), 'symbols': {}}
        self.state = self.root/'source.p2s'
        self.save(self.state)

    def save(self, path):
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('eeMemory.bin', self.memory)

    def test_profile_matches_number_of_players_and_has_portable_symbols(self):
        import json
        create_profile(self.state, self.meta, 4, 'PCSX2 2.8.2', self.root/'first')
        metadata = {**self.meta, 'disc_path': '/another/pc/game.iso', 'boot_path': '/another/pc/hook.elf'}
        create_profile(self.state, metadata, 4, 'PCSX2 2.8.2', self.root/'second')
        first = json.loads((self.root/'first/manifest.json').read_text())
        second = json.loads((self.root/'second/manifest.json').read_text())
        self.assertEqual(first, second)
        self.assertEqual(first['disc_sha256'], self.meta['disc_sha256'])
        self.assertEqual(len(first['pads']), 4)
        with self.assertRaisesRegex(ValueError, 'ya existe'):
            create_profile(self.state, self.meta, 4, 'PCSX2 2.8.2', self.root/'first')

    def test_cannot_label_four_player_state_as_two_or_three(self):
        for count in (2, 3):
            with self.assertRaisesRegex(ValueError, 'cantidad'):
                create_profile(self.state, self.meta, count, 'PCSX2 2.8.2', self.root/str(count))

    def test_rejects_a_running_state_or_other_hook_build(self):
        struct.pack_into('<I', self.memory, self.base+20, 0)  # hold released
        self.save(self.state)
        with self.assertRaisesRegex(ValueError, 'congelado'):
            create_profile(self.state, self.meta, 4, 'PCSX2 2.8.2', self.root/'running')
        struct.pack_into('<I', self.memory, self.base+20, 1)
        self.save(self.state)
        with self.assertRaisesRegex(ValueError, 'compilación'):
            create_profile(self.state, {**self.meta, 'code_sha256': '0'*64}, 4, 'PCSX2 2.8.2', self.root/'other')

    def test_catalog_selects_each_count_and_rejects_changed_state(self):
        for count in (2, 3, 4):
            folder = self.root/'profiles'/f'{count}p'/'revision-1'
            folder.mkdir(parents=True)
            state = folder/'DON-organicense.p2s'
            struct.pack_into('<I', self.memory, self.base+52, count)
            self.save(state)
            create_profile(state, self.meta, count, 'PCSX2 2.8.2', folder)
        root = self.root/'profiles'
        result = index_profiles(root, self.meta)
        self.assertEqual(set(result['profiles']), {'2', '3', '4'})
        for count in (2, 3, 4):
            selected = select_profile(root, count, self.meta)
            self.assertEqual(selected['players'], count)
            self.assertIn(f'/{count}p/', selected['state'])
        selected = select_profile(root, 3)
        Path(selected['state']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'cambiaron'):
            select_profile(root, 3)
        with self.assertRaisesRegex(ValueError, 'otra ISO'):
            select_profile(root, 4, {**self.meta, 'disc_sha256': 'd'*64})

    def test_prepare_restores_controls_and_never_overwrites_an_existing_snapshot(self):
        core = Mock()
        core.get.side_effect = lambda name: {'captures': 1, 'status': 2}[name]
        state_dir = self.root/'empty'
        state_dir.mkdir()
        core.pine.save_state.side_effect = lambda slot: self.save(state_dir/f'fixture.{slot:02}.p2s')
        output = self.root/'new.p2s'
        result = prepare_state(core, state_dir, output, capacity=4)
        self.assertEqual(result['players'], 4)
        core.arm.assert_called_once_with(4)
        core.stop.assert_called_once()
        original = output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'ya existe'):
            prepare_state(core, state_dir, output, capacity=4)
        self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
