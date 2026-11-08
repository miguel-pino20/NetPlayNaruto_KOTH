import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from disc_image import BLOCK, ElfImage, IsoImage, inspect_disc, pcsx2_crc


def make_elf():
    data = bytearray(256)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHI', data, 16, 2, 8, 1)
    struct.pack_into('<III', data, 24, 0x100008, 52, 0)
    struct.pack_into('<HHHHHH', data, 40, 52, 32, 1, 40, 0, 0)
    struct.pack_into('<8I', data, 52, 1, 128, 0x100000, 0x100000, 128, 256, 7, 128)
    data[128:132] = b'TEST'
    return bytes(data)


def record(name, extent, size, directory=False):
    length = 33+len(name)+(1 if len(name) % 2 == 0 else 0)
    data = bytearray(length)
    data[0] = length
    struct.pack_into('<I', data, 2, extent)
    struct.pack_into('>I', data, 6, extent)
    struct.pack_into('<I', data, 10, size)
    struct.pack_into('>I', data, 14, size)
    data[25], data[28], data[31], data[32] = 2 if directory else 0, 1, 1, len(name)
    data[33:33+len(name)] = name
    return data


def make_iso():
    data = bytearray(BLOCK*32)
    pvd = memoryview(data)[BLOCK*16:BLOCK*17]
    pvd[:7] = b'\x01CD001\x01'
    struct.pack_into('<I', pvd, 80, 32)
    struct.pack_into('>I', pvd, 84, 32)
    struct.pack_into('<H', pvd, 128, BLOCK)
    struct.pack_into('>H', pvd, 130, BLOCK)
    root = record(b'\0', 20, BLOCK, True)
    pvd[156:156+len(root)] = root
    data[BLOCK*17:BLOCK*17+7] = b'\xffCD001\x01'
    config = b'BOOT2 = cdrom0:\\SLPS_256.75;1\r\nVER = 1.02\r\n'
    elf = make_elf()
    directory = (root+record(b'\1', 20, BLOCK, True)+record(b'SYSTEM.CNF;1', 22, len(config))
                 +record(b'SLPS_256.75;1', 24, len(elf)))
    data[BLOCK*20:BLOCK*20+len(directory)] = directory
    data[BLOCK*22:BLOCK*22+len(config)] = config
    data[BLOCK*24:BLOCK*24+len(elf)] = elf
    return data


class DiscImageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'fixture.iso'
        self.path.write_bytes(make_iso())

    def test_identifies_boot_elf_and_leaves_image_unchanged(self):
        original = self.path.read_bytes()
        result, elf = inspect_disc(self.path)
        self.assertEqual(result['serial'], 'SLPS-25675')
        self.assertEqual(result['elf_sha256'], hashlib.sha256(make_elf()).hexdigest())
        self.assertEqual(result['pcsx2_crc'], pcsx2_crc(make_elf()))
        self.assertEqual(elf.read_virtual(0x100000, 4), b'TEST')
        self.assertEqual(self.path.read_bytes(), original)

    def test_crc_xors_words_and_ignores_incomplete_word(self):
        self.assertEqual(pcsx2_crc(struct.pack('<II', 0x12345678, 0xAABBCCDD)+b'123'), 'B88F9AA5')

    def test_rejects_out_of_image_file_reference(self):
        data = make_iso()
        # The SYSTEM.CNF record follows the two 34-byte dot entries.
        struct.pack_into('<I', data, BLOCK*20+68+2, 100)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'fuera'):
            inspect_disc(self.path)

    def test_rejects_truncated_image_and_unsupported_block_size(self):
        self.path.write_bytes(make_iso()[:-BLOCK])
        with self.assertRaisesRegex(ValueError, 'truncada'):
            inspect_disc(self.path)
        data = make_iso()
        struct.pack_into('<H', data, BLOCK*16+128, 512)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'sector'):
            inspect_disc(self.path)

    def test_rejects_traversal_and_missing_files(self):
        with IsoImage(self.path) as iso:
            for name in ('../SYSTEM.CNF', 'MISSING', 'SYSTEM.CNF/FILE'):
                with self.assertRaises(ValueError):
                    iso.read_file(name)

    def test_elf_requires_mips_and_file_backed_ranges(self):
        elf = ElfImage(make_elf())
        with self.assertRaises(ValueError):
            elf.read_virtual(0x100080, 4)  # BSS, not file data
        data = bytearray(make_elf())
        struct.pack_into('<H', data, 18, 3)
        with self.assertRaisesRegex(ValueError, 'MIPS'):
            ElfImage(data)


if __name__ == '__main__':
    unittest.main()
