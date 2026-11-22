"""Exercise the real UDP handshake with a simulated clock and game-path latency."""
import unittest
from unittest.mock import Mock, patch

import node
import wire


class DelayTests(unittest.TestCase):
    def play(self, link_ms, *, host_auto=True, guest_auto=True):
        clock = 10000
        pending = []
        dropped = []
        core = Mock()
        core.captured.return_value = {}
        core.hashes.return_value = {}
        host = node.Node(core, 1, 0, 0, [0, 1], generic=True, first_capture=1)
        guest = node.Node(core, 2, 1, 0, [0, 1], generic=True, first_capture=1,
                          host=('127.0.0.1', host.sock.getsockname()[1]))
        for player, auto in ((host, host_auto), (guest, guest_auto)):
            self.addCleanup(player.sock.close)
            player.calibrate_delay = auto
            player.sel_sync = False
            def transmit(peer, packet, sender=player):
                message = wire.parse(packet)
                # Lose the first HELLO carrying the final host decision.
                if sender.is_host and message.get('auto_delay') and not dropped:
                    dropped.append(True)
                    return
                pending.append((clock + link_ms, sender, packet, peer.addr))
            player._tx = transmit
        with patch('node.time.perf_counter', side_effect=lambda: clock / 1000), \
             patch('node.time.monotonic', side_effect=lambda: clock / 1000):
            for clock in range(10000, 17500, 5):
                due = [item for item in pending if item[0] <= clock]
                for item in due:
                    pending.remove(item)
                    _, sender, packet, addr = item
                    sender.sock.sendto(packet, addr)
                host.pump()
                guest.pump()
                if host.started and guest.started:
                    break
        self.assertTrue(host.started and guest.started)
        self.assertEqual(host.delay, guest.delay)
        self.assertEqual(host.known[0], guest.known[0])
        self.assertEqual(bool(dropped), host_auto and guest_auto)
        return host.delay

    def test_peer_measurement_and_retransmission(self):
        for latency, expected in ((90, 3), (100, 3), (140, 5)):
            with self.subTest(rtt=2 * latency):
                self.assertEqual(self.play(latency), expected)

    def test_fixed_host_or_older_guest_uses_session_delay(self):
        self.assertEqual(self.play(140, host_auto=False), 3)
        self.assertEqual(self.play(140, guest_auto=False), 3)

    def test_single_spike_does_not_choose_delay_for_whole_match(self):
        host = node.Node(Mock(), 1, 0, 0, [0, 1])
        self.addCleanup(host.sock.close)
        host.calibrate_delay = True
        host.probe_started = 1
        host.delay_samples = [180, 182, 189, 192, 190, 188, 194, 197, 200, 280]
        self.assertEqual(host._hello_choice(2000), 3)
