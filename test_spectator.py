import queue
import socket
import time
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import core_link
import node
import netlink
import spectator
import wire
from simgame import BASE, SimGame


class MemoryPine:
    def __init__(self):
        self.m, self.sock = {}, object()

    def read(self, address, size=4):
        # PineCore uses 64-bit ring entries; header fields use individual words.
        return self.m.get(address, 0)

    def write(self, address, value, size=4):
        self.m[address] = value

    def batch(self, ops):
        values = []
        for op in ops:
            if op[0] == 'r':
                values.append(self.read(op[1], op[2]))
            else:
                self.write(*op[1:])
        return values


def source(count=8):
    known = {slot: {f: (bytes([slot+f])*24, f) for f in range(count)} for slot in (0, 1)}
    return SimpleNamespace(known=known, need={0: count, 1: count}, cap_next=count, sel_words=None)


class SpectatorTests(unittest.TestCase):
    def server(self):
        server = spectator.ReplayServer(0, 'secret-round', 'a'*16, 'b'*16, 3, bind='127.0.0.1')
        self.addCleanup(server.close)
        return server

    def client(self, server):
        client = spectator.ReplayClient(('127.0.0.1', server.port), 'secret-round', 'a'*16, 'b'*16, 3)
        self.addCleanup(client.close)
        return client

    def frames(self, client, count):
        result = []
        while len(result) < count:
            record = client.records.get(timeout=2)
            if not record[0] & spectator.SELECTION_EVENT:
                result.append(record)
        return result

    def test_late_spectator_receives_complete_input_history_and_disconnect_does_not_stop_host(self):
        server = self.server()
        host = source()
        server.capture(host)
        client = self.client(server)
        records = self.frames(client, 8)
        self.assertEqual([r[0] for r in records], list(range(8)))
        self.assertEqual(records[5][1:5], (*host.known[0][5], *host.known[1][5]))
        client.close()
        self.assertFalse(server.done.is_set())
        host = source(9)
        server.capture(host)
        another = self.client(server)
        self.assertEqual([r[0] for r in self.frames(another, 9)], list(range(9)))

    def test_wrong_round_and_manifest_are_rejected(self):
        server = self.server()
        for key, tag in [('old-round', 'a'*16), ('secret-round', 'c'*16)]:
            with self.assertRaises((EOFError, OSError)):
                spectator.ReplayClient(('127.0.0.1', server.port), key, tag, 'b'*16, 3)

    def test_stalled_spectator_and_archive_limits_do_not_change_players(self):
        server = spectator.ReplayServer.__new__(spectator.ReplayServer)
        server.done, server.cursor = threading.Event(), 0
        server.last_selection, server.last_event = None, 0
        server.pending = queue.Queue(maxsize=1)
        host = source(4)
        # Stop the archive worker from consuming this replacement queue.
        server.pending.put(b'busy')
        before = dict(host.need)
        server.capture(host)
        self.assertTrue(server.done.is_set())
        self.assertEqual(host.need, before)

    def test_replay_applies_both_slots_and_ignores_spectators_local_pad(self):
        memory = MemoryPine()
        core = core_link.PineCore(BASE, pine=memory, serial=None)
        core.arm()
        game = SimGame(memory, lambda frame: b'LOCAL INPUT MUST NOT BE USED'[:24])
        records = queue.Queue()
        host = source(100)
        host.known = {slot: {frame: (item[0], 0) for frame, item in frames.items()}
                      for slot, frames in host.known.items()}
        for frame in range(100):
            records.put(spectator.FRAME.unpack(spectator.FRAME.pack(
                frame, *host.known[0][frame], *host.known[1][frame], *([0]*14))))
        player = spectator.ReplayPlayer(core, records)
        for _ in range(600):
            game.step()
            player.step()
        self.assertEqual(len(game.applied), 100)
        for frame, raw0, raw1 in game.applied:
            self.assertEqual(raw0, host.known[0][frame][0])
            self.assertEqual(raw1, host.known[1][frame][0])
        self.assertEqual(core.get('abort'), 0)
        self.assertEqual(core.get('hold'), 1)

    def test_out_of_order_stream_only_fails_spectator(self):
        core = SimpleNamespace(get=lambda name: 10)
        records = queue.Queue()
        records.put((3, bytes(24), 0, bytes(24), 0, *([0]*14)))
        with self.assertRaises(ValueError):
            spectator.ReplayPlayer(core, records).step()

    def test_selection_updates_during_idle_without_local_input_or_ring_writes(self):
        core = Mock()
        core.get.return_value = 1
        records = queue.Queue()
        selection = [1] + list(range(13))
        records.put((spectator.SELECTION_EVENT | 1, bytes(24), 0, bytes(24), 0, *selection))
        player = spectator.ReplayPlayer(core, records)
        self.assertTrue(player.step())
        core.follow_selection.assert_called_once_with(selection)
        core.publish.assert_not_called()
        self.assertEqual(player.next, 0)

    def test_spectator_never_joins_udp_player_handshake(self):
        host = node.Node(SimpleNamespace(), 1, 0, 0, [0, 1])
        self.addCleanup(host.close)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        packet = wire.hello(3, host.session, 0, 0, delay=3, tag=host.tag, slot=None)
        sender.sendto(packet, ('127.0.0.1', host.sock.getsockname()[1]))
        deadline = time.monotonic()+1
        while time.monotonic() < deadline:
            host._recv()
            if host.peers:
                break
            time.sleep(0.002)
        self.assertEqual(host.peers, {})
        self.assertFalse(host.ready())

    def test_two_players_and_late_spectator_reproduce_the_same_simulated_fight(self):
        cores, games = [], []
        for slot in range(3):
            core = core_link.PineCore(BASE, pine=MemoryPine(), serial=None)
            core.arm()
            game = SimGame(core.pine, lambda f, s=slot: bytes([s+1, f % 256])*12)
            game.step()  # The save state sits frozen after the initial capture.
            cores.append(core)
            games.append(game)
        host = node.Node(cores[0], 1, 0, 0, [0, 1], first_capture=1)
        guest = node.Node(cores[1], 2, 1, 0, [0, 1], first_capture=1,
                          host=('127.0.0.1', host.sock.getsockname()[1]))
        self.addCleanup(host.close)
        self.addCleanup(guest.close)
        server = self.server()
        host.replay = server
        observer = None
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            for network, game in zip((host, guest), games[:2]):
                network.pump()
                if network.started:
                    network.core.release()
                game.step()
            if observer is None and len(games[0].applied) >= 20:
                client = self.client(server)
                observer = spectator.ReplayPlayer(cores[2], client.records)
            if observer:
                games[2].step()
                observer.step()
            if len(games[2].applied) >= 80:
                break
            time.sleep(0.0005)
        self.assertGreaterEqual(len(games[2].applied), 80)
        self.assertEqual(games[0].applied[:80], games[1].applied[:80])
        self.assertEqual(games[0].applied[:80], games[2].applied[:80])
        self.assertEqual(set(host.peers), {2})
        self.assertIsNone(host.desync)

    def test_principal_relay_carries_entire_fight_without_direct_probes(self):
        relay = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        relay.bind(('127.0.0.1', 0))
        relay.setblocking(False)
        self.addCleanup(relay.close)
        address = relay.getsockname()
        token = b'12345678'
        cores, games = [], []
        for slot in (0, 1):
            core = core_link.PineCore(BASE, pine=MemoryPine(), serial=None)
            core.arm()
            game = SimGame(core.pine, lambda f, s=slot: bytes([s+1, f % 256])*12)
            game.step()
            cores.append(core)
            games.append(game)
        host = node.Node(cores[0], 1, 0, 0, [0, 1], first_capture=1, relay=(address, token), relay_only=True)
        guest = node.Node(cores[1], 2, 1, 0, [0, 1], first_capture=1, relay=(address, token), relay_only=True,
                          host=('10.147.0.1', 47400), cands=[('10.147.0.2', 47400)])
        self.addCleanup(host.close)
        self.addCleanup(guest.close)
        host.add_expected_peer(2, 1, ('10.147.0.2', 47400))
        host._send_direct = Mock(side_effect=AssertionError('Direct game packet'))
        guest._send_direct = Mock(side_effect=AssertionError('Direct game packet'))
        ports = [network.sock.getsockname()[1] for network in (host, guest)]
        relayed = 0
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            for network, game in zip((host, guest), games):
                network.pump()
                if network.started:
                    network.core.release()
                game.step()
            while True:
                try:
                    packet, sender = relay.recvfrom(2048)
                except BlockingIOError:
                    break
                if packet[:5] == netlink.MAGIC+b'F':
                    self.assertEqual(packet[5:13], token)
                    destination = ports[1] if sender[1] == ports[0] else ports[0]
                    relay.sendto(netlink.MAGIC+b'D'+packet[13:], ('127.0.0.1', destination))
                    relayed += 1
            if min(len(game.applied) for game in games) >= 80:
                break
            time.sleep(0.0005)
        self.assertGreater(relayed, 0)
        self.assertGreaterEqual(min(len(game.applied) for game in games), 80)
        self.assertEqual(games[0].applied[:80], games[1].applied[:80])
        host._send_direct.assert_not_called()
        guest._send_direct.assert_not_called()
        self.assertIsNone(host.desync)


if __name__ == '__main__':
    unittest.main()
