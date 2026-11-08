import configparser
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_don import BASE, RESERVE, make_boot
from disc_image import ElfImage
from don_test_session import prepare


def fixture_elf():
    size = 0x3bc358-0x100000+0x80
    data = bytearray(size)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHI', data, 16, 2, 8, 1)
    struct.pack_into('<III', data, 24, 0x100008, 52, 0)
    struct.pack_into('<HHHHHH', data, 40, 52, 32, 2, 40, 0, 0)
    struct.pack_into('<8I', data, 52, 1, 128, 0x100000, 0x100000, size-128, BASE-0x100000, 7, 128)
    struct.pack_into('<8I', data, 84, 1, size, BASE, BASE, 0, 0, 6, 16)
    words = {0x100120: 0x3C03005A, 0x1001D0: 0x3C04005A, 0x1365DC: 0x3C02005A,
             0x138B14: 0x0C04E3EC, 0x118E38: 0x0080382D, 0x118E3C: 0x24030070,
             0x3BC354: 0x005A6800}
    for address, word in words.items():
        struct.pack_into('<I', data, address-0x100000+128, word)
    return bytes(data)


class DonBuildTests(unittest.TestCase):
    def test_reserves_kernel_heap_big_pool_and_libkernel_break(self):
        data = fixture_elf()
        original = ElfImage(data)
        with patch('build_don.ELF_SHA256', hashlib.sha256(data).hexdigest()):
            result = make_boot(original, b'LOCAL_PAYLOAD!!!', {'np4_poll_entry': BASE, 'np4_read_entry': BASE+16})
        changed = ElfImage(result)
        self.assertEqual(struct.unpack('<I', changed.read_virtual(0x1001D0, 4))[0], 0x3C04005B)
        self.assertEqual(struct.unpack('<I', changed.read_virtual(0x1365DC, 4))[0], 0x3C02005B)
        self.assertEqual(struct.unpack('<I', changed.read_virtual(0x3BC354, 4))[0], 0x005B6800)
        self.assertEqual(changed.read_virtual(0x100120, 4), original.read_virtual(0x100120, 4))
        self.assertEqual(changed.read_virtual(BASE, 16), b'LOCAL_PAYLOAD!!!')
        self.assertEqual(changed.segments[-1][3], RESERVE)
        self.assertEqual(original.data, data)

    def test_test_session_uses_separate_settings_card_and_writable_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root/'original', root/'test'
            (source/'inis').mkdir(parents=True)
            (source/'bios').mkdir()
            (source/'bios/test.bin').write_bytes(b'fixture')
            original = ('[Folders]\nBios=bios\nMemoryCards=/original/cards\nLogs=/original/logs\n'
                        '[Filenames]\nBIOS=test.bin\n[MemoryCards]\nSlot1_Filename=original.ps2\n'
                        '[EmuCore]\nPINESlot=28011\n')
            (source/'inis/PCSX2.ini').write_text(original)
            boot, iso, card = root/'boot.elf', root/'disc.iso', root/'card.ps2'
            for file, value in ((boot, b'elf'), (iso, b'iso'), (card, b'unlocked-card')):
                file.write_bytes(value)
            adapter = root/'adapter.json'
            adapter.write_text(json.dumps({'experimental': True, 'adapter': 'don-experimental-input-v1',
                                           'boot_path': str(boot), 'disc_path': str(iso)}))
            result = prepare(adapter, source, target, card)
            cfg = configparser.ConfigParser()
            cfg.read(target/'PCSX2/inis/PCSX2.ini')
            self.assertEqual(cfg.get('EmuCore', 'PINESlot'), '28012')
            self.assertEqual(Path(cfg.get('Folders', 'MemoryCards')), target/'PCSX2/memcards')
            self.assertEqual((target/'PCSX2/memcards/DON-Latino-test.ps2').read_bytes(), card.read_bytes())
            self.assertEqual((source/'inis/PCSX2.ini').read_text(), original)
            self.assertIn(f'--filesystem={iso}:ro', result['command'])
            with self.assertRaises(FileExistsError):
                prepare(adapter, source, target, card)
            custom = root/'test-28011'
            result = prepare(adapter, source, custom, card, pine_slot=28011)
            cfg.read(custom/'PCSX2/inis/PCSX2.ini')
            self.assertEqual(cfg.get('EmuCore', 'PINESlot'), '28011')
            self.assertEqual(result['pine_slot'], 28011)


if __name__ == '__main__':
    unittest.main()
