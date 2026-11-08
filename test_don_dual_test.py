"""Checks for the diagnostic's exact-frame stopping and distinct player input."""
import struct
import unittest

from don_dual_test import DiagnosticCore, scripted_pad
from wire import IDLE_PAD


class Core:
    def __init__(self):
        self.inputs = [{}, {}]

    def publish(self, slot, frames):
        self.inputs[slot].update(frames)

    def captured(self, first, limit):
        return {first: (IDLE_PAD, 99)}


class DualDiagnosticTests(unittest.TestCase):
    def test_barrier_retains_lookahead_and_releases_each_slot_at_next_checkpoint(self):
        core = Core()
        diagnostic = DiagnosticCore(core, 0, 3)
        frames = {f: (bytes([f])*24, f) for f in range(8)}
        for slot in range(2):
            diagnostic.publish(slot, frames)
            self.assertEqual(set(core.inputs[slot]), {0, 1, 2})
        diagnostic.extend(6)
        for slot in range(2):
            self.assertEqual(set(core.inputs[slot]), set(range(6)))
            self.assertEqual(set(diagnostic.pending[slot]), {6, 7})
            self.assertEqual(core.inputs[slot][5], frames[5])
        with self.assertRaises(ValueError):
            diagnostic.extend(6)

    def test_start_is_host_only_and_combat_actions_differ_by_player(self):
        self.assertEqual(struct.unpack_from('<H', scripted_pad(20, 0), 2)[0], 0xfff7)
        self.assertEqual(scripted_pad(20, 1), IDLE_PAD)
        self.assertEqual(scripted_pad(25, 0), IDLE_PAD)
        self.assertNotEqual(scripted_pad(600, 0), scripted_pad(600, 1))
        self.assertEqual(len(scripted_pad(600, 0)), 24)
        # At frame 120 both players confirm and supply the matching pressure.
        for slot in range(2):
            raw = scripted_pad(120, slot)
            self.assertEqual(struct.unpack_from('<H', raw, 2)[0], 0xdfff)
            self.assertEqual(raw[13], 255)


if __name__ == '__main__':
    unittest.main()
