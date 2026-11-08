"""Exercise the real C barrier through the Python PINE ABI, including ring wrap."""
import ctypes
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from build_don import BASE, RESERVE, SHARED_SIZE, jump
from don_core import DonCore, HEADER, INPUTS, loopback
from don_adapter import MULTITAP_MODE, PAD_COUNT, PAD_INITIALIZED, PAD_RECORDS, PAD_STRIDE
from mips_link import link
from wire import IDLE_PAD


class NativePine:
    def __init__(self, native):
        self.native = native
        self.words = (ctypes.c_uint32*(SHARED_SIZE//4)).in_dll(native, 'g_np4')
        self.memory = (ctypes.c_ubyte*SHARED_SIZE).from_address(ctypes.addressof(self.words))
        self.shared = BASE+0x1000
        self.other = {}
        self.load(BASE, b'codecode')
        self.load(0x138B14, struct.pack('<I', jump(BASE, True)))
        self.load(0x118E38, struct.pack('<II', jump(BASE+0x100), 0))
        for address, value in ((MULTITAP_MODE, 1), (PAD_COUNT, 4), (PAD_INITIALIZED, 1)):
            self.load(address, struct.pack('<I', value))
        for slot in range(4):
            self.load(PAD_RECORDS+slot*PAD_STRIDE, struct.pack('<h', 99))
            self.load(PAD_RECORDS+slot*PAD_STRIDE+4, struct.pack('<h', 6))
        ctypes.memset(ctypes.addressof(self.words), 0, SHARED_SIZE)
        self.words[0:3] = (0x34504e44, 1, SHARED_SIZE)
        self.words[12] = 1
        self.meta = {'schema': 1, 'payload_base': BASE, 'reserve_size': RESERVE,
                     'shared_base': self.shared, 'shared_size': SHARED_SIZE, 'code_size': 8,
                     'code_sha256': hashlib.sha256(b'codecode').hexdigest(),
                     'boot_crc': '11223344', 'source_crc': '82EA02B7',
                     'symbols': {'np4_poll_entry': BASE, 'np4_read_entry': BASE+0x100}}

    def load(self, address, data):
        self.other.update({address+i: value for i, value in enumerate(data)})

    def game_crc(self):
        return '11223344'

    def read(self, address, size=4):
        return int.from_bytes(bytes(self.memory[address+i-self.shared] if self.shared <= address+i < self.shared+SHARED_SIZE
                                    else self.other.get(address+i, 0) for i in range(size)), 'little')

    def write(self, address, value, size=4):
        if not self.shared <= address <= self.shared+SHARED_SIZE-size:
            raise AssertionError('Write outside shared memory')
        for i, byte in enumerate(value.to_bytes(size, 'little')):
            self.memory[address+i-self.shared] = byte

    def batch(self, ops):
        values = []
        for op in ops:
            if op[0] == 'r':
                values.append(self.read(op[1], op[2]))
            else:
                self.write(op[1], op[2], op[3])
        return values


@unittest.skipUnless(shutil.which('clang'), 'clang is needed to verify native C / MIPS ABI')
class DonHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        stub = root/'stub.c'
        stub.write_text('int np4_read_original(int p,int s,void *d){return 0;}\n')
        so = root/'barrier.so'
        src = Path(__file__).resolve().parent/'don_hook/netpad4.c'
        subprocess.run(['clang', '-shared', '-fPIC', '-O2', str(src), str(stub), '-o', str(so)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cls.native = ctypes.CDLL(str(so))
        cls.native.np4_exchange.argtypes = [ctypes.c_void_p]
        cls.native.np4_exchange.restype = ctypes.c_int
        cls.native.np4_read.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        self.pine = NativePine(self.native)
        self.core = DonCore(self.pine, self.pine.meta)

    def run_native_loopback(self, capacity, restored=False):
        stop = threading.Event()
        raw = ctypes.create_string_buffer(IDLE_PAD)

        def game():
            while not stop.is_set():
                if self.pine.words[3] and not self.pine.words[4]:
                    if self.native.np4_exchange(raw):
                        self.pine.words[8] += 1
                else:
                    time.sleep(0.0001)

        worker = threading.Thread(target=game, daemon=True)
        if restored:
            self.core.arm(capacity)
        worker.start()
        try:
            if restored:
                deadline = time.monotonic()+1
                while not self.core.frozen(capacity) and time.monotonic() < deadline:
                    time.sleep(0.001)
            result = loopback(self.core, frames=300, control=capacity-1, timeout=5, capacity=capacity, restored=restored)
            self.assertGreaterEqual(result['frames'], 300)
            self.assertEqual(result['virtual_player'], capacity)
            self.assertEqual(result['players'], capacity)
            self.assertFalse(self.core.simulation_hashes)
            self.assertFalse(result['online_verified'])
            self.assertEqual(self.core.get('active'), 0)
        finally:
            stop.set()
            self.core.stop()
            worker.join(1)
        self.assertFalse(worker.is_alive())

    def test_python_driver_runs_300_frames_against_compiled_c(self):
        self.run_native_loopback(4)

    def test_two_players_keep_inactive_slots_neutral_without_waiting_for_peers(self):
        self.run_native_loopback(2)

    def test_three_players_keep_fourth_slot_neutral(self):
        self.run_native_loopback(3)

    def test_restored_state_ignores_creators_first_capture_and_crosses_ring_wrap(self):
        self.run_native_loopback(3, restored=True)

    def test_barrier_waits_for_fourth_pad_then_applies_each_slot(self):
        self.core.arm()
        raw = ctypes.create_string_buffer(IDLE_PAD)
        result = []
        worker = threading.Thread(target=lambda: result.append(self.native.np4_exchange(raw)), daemon=True)
        worker.start()
        values = [bytes([slot+1])*24 for slot in range(4)]
        try:
            self.core.release()
            for slot in range(3):
                self.core.publish(slot, {0: (values[slot], 0)})
            deadline = time.monotonic()+1
            while self.core.get('missing') != 8 and time.monotonic() < deadline:
                time.sleep(0.001)
            self.assertEqual(self.core.get('missing'), 8)
            self.assertTrue(worker.is_alive())
            self.core.publish(3, {0: (values[3], 0)})
            worker.join(1)
            self.assertEqual(result, [1])
            for slot in range(4):
                buffer = ctypes.create_string_buffer(32)
                self.assertEqual(self.native.np4_read(0, slot, buffer), 32)
                self.assertEqual(buffer.raw[:24], values[slot])
            self.assertEqual(self.core.get('captures'), 1)
        finally:
            self.core.stop()
            worker.join(1)

    def test_rejects_bad_slot_and_unsupported_runtime_before_writing(self):
        with self.assertRaises(ValueError):
            self.core.publish(4, {0: (IDLE_PAD, 0)})
        self.pine.load(BASE, bytes(8))
        with self.assertRaisesRegex(ValueError, 'ejecutable experimental'):
            DonCore(self.pine, self.pine.meta)
        self.assertEqual(self.core.get('active'), 0)

    def test_mips_linker_resolves_signed_low_halves_and_external_jumps(self):
        root = Path(self.folder.name)
        a, b = root/'a.S', root/'b.S'
        a.write_text('.set noreorder\n.text\n.globl entry\nentry:\n'
                     'lui $2,%hi(value)\naddiu $2,$2,%lo(value)\njal ext\nnop\njr $31\nnop\n'
                     '.data\n.globl value\nvalue: .word entry\n')
        b.write_text('.set noreorder\n.text\n.globl ext\next:\njr $31\nnop\n')
        objects = []
        for source in (a, b):
            obj = source.with_suffix('.o')
            subprocess.run(['clang', '--target=mipsel-none-elf', '-march=mips3', '-mabi=32', '-mno-abicalls',
                            '-fno-pic', '-G0', '-c', str(source), '-o', str(obj)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            objects.append(obj)
        base = 0x5A7FF0  # data crosses 0x8000: HI16 must carry, LO16 becomes negative
        payload, symbols = link(objects, base, 4096)
        hi, lo, target = struct.unpack_from('<III', payload)
        signed_low = ctypes.c_int16(lo & 65535).value
        self.assertEqual(((hi & 65535)<<16)+signed_low, symbols['value'])
        self.assertEqual((target & 0x3ffffff)<<2, symbols['ext'])
        self.assertEqual(struct.unpack_from('<I', payload, symbols['value']-base)[0], symbols['entry'])


if __name__ == '__main__':
    unittest.main()
