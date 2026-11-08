import hashlib
import struct
import unittest
from unittest.mock import patch

import don_adapter as don


class ReadOnlyPine:
    def __init__(self, mode=1, count=4):
        self.memory = {}
        self.reads = 0
        for address, value in ((don.MULTITAP_MODE, mode), (don.PAD_COUNT, count),
                               (don.PAD_INITIALIZED, 1), (don.VBLANK_PENDING, 1)):
            self.load(address, struct.pack('<I', value))
        self.load(0x100000, b'fixture!')
        for slot in range(4):
            record = bytearray(don.PAD_STRIDE)
            struct.pack_into('<h', record, 0, 99)
            struct.pack_into('<h', record, 4, 6)
            struct.pack_into('<I', record, 12, 1 << slot)
            self.load(don.PAD_RECORDS+slot*don.PAD_STRIDE, record)

    def load(self, address, data):
        self.memory.update({address+i: value for i, value in enumerate(data)})

    def game_id(self):
        return 'SLPS_256.75'

    def game_crc(self):
        return don.CRC

    def read(self, address, size=4):
        self.reads += 1
        return int.from_bytes(bytes(self.memory.get(address+i, 0) for i in range(size)), 'little')

    def batch(self, ops):
        if any(op[0] != 'r' for op in ops):
            raise AssertionError('El diagnóstico intentó escribir memoria.')
        return [self.read(address, size) for _, address, size in ops]


class DonProbeTests(unittest.TestCase):
    def setUp(self):
        self.ranges = patch.dict(don.CODE_RANGES, {'fixture': (0x100000, 8, hashlib.sha256(b'fixture!').hexdigest())}, clear=True)
        self.ranges.start()
        self.addCleanup(self.ranges.stop)

    def test_reads_four_real_slots_without_enabling_netplay(self):
        result = don.probe(ReadOnlyPine())
        self.assertTrue(result['four_pad_mode'])
        self.assertTrue(result['read_only'])
        self.assertFalse(result['netplay_available'])
        self.assertFalse(result['sample_atomic'])
        self.assertEqual([p['slot'] for p in result['players']], [1, 2, 3, 4])
        self.assertEqual([p['held'] for p in result['players']], ['00000001', '00000002', '00000004', '00000008'])

    def test_two_pad_mode_does_not_claim_four_slots(self):
        result = don.probe(ReadOnlyPine(mode=0, count=2))
        self.assertFalse(result['four_pad_mode'])
        self.assertEqual([(p['port'], p['slot']) for p in result['players']], [(1, 1), (2, 1)])

    def test_wrong_game_is_rejected_before_memory_reads(self):
        pine = ReadOnlyPine()
        pine.game_crc = lambda: '00000000'
        with self.assertRaisesRegex(ValueError, 'D.O.N Japan'):
            don.probe(pine)
        self.assertEqual(pine.reads, 0)

    def test_unexpected_code_is_rejected_before_pad_structures(self):
        pine = ReadOnlyPine()
        pine.load(0x100000, bytes(8))
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            don.probe(pine)
        self.assertEqual(pine.reads, 1)

    def test_byte_reader_handles_unaligned_sizes_and_multiple_batches(self):
        pine = ReadOnlyPine()
        data = bytes(i % 256 for i in range(1615))
        pine.load(0x200000, data)
        self.assertEqual(don.read_bytes(pine, 0x200000, len(data)), data)


if __name__ == '__main__':
    unittest.main()
