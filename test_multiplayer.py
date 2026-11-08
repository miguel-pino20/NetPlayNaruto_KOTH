"""Four-node protocol tests without PCSX2 or a configured VPN."""
import copy
import hashlib
import struct
import time
import unittest
from collections import deque
from unittest.mock import patch

from multiplayer_client import RoomClient, make_node, watch
from node import NEUTRAL, Node, NULL_STATE_HASH
import wire


class MemorySocket:
    def __init__(self, network, address):
        self.network, self.address, self.queue = network, address, deque()
        network[address] = self

    def setblocking(self, value):
        pass

    def sendto(self, data, address):
        if address in self.network:
            self.network[address].queue.append((data, self.address))

    def recvfrom(self, size):
        return self.queue.popleft()

    def close(self):
        self.network.pop(self.address, None)


class FourPadCore:
    """Advances only after all four published pads exist; hashes their history."""
    max_players = 4
    adapter_id = 'don-test-v1'

    def __init__(self, slot):
        self.slot, self.frame = slot, 0
        self.inputs = {s: {} for s in range(4)}
        self.outputs, self.history = {}, {}
        self.digest = bytes(32)
        self.capture()

    def capture(self):
        self.outputs[self.frame] = (bytes([self.slot+1, self.frame % 256])*12, self.frame)

    def captured(self, first, limit):
        return {f: self.outputs[f] for f in range(first, first+limit) if f in self.outputs}

    def publish(self, slot, frames):
        self.inputs[slot].update(frames)

    def hashes(self, first, limit):
        return {f: self.history[f] for f in range(first, first+limit) if f in self.history}

    def step(self):
        if all(self.frame in self.inputs[s] for s in range(4)):
            pads = b''.join(self.inputs[s][self.frame][0] for s in range(4))
            self.digest = hashlib.sha256(self.digest + pads).digest()
            self.history[self.frame] = struct.unpack('<I', self.digest[:4])[0]
            self.frame += 1
            self.capture()


class MultiplayerClientTests(unittest.TestCase):
    def snapshot(self):
        pads = [{'port': 1, 'slot': s} for s in range(1, 5)]
        return {'status': 'running', 'ready': True, 'transport': 'zerotier', 'capacity': 4,
                'slot': 0, 'delay': 3, 'session_epoch': '12345678-1234-1234-1234-123456789abc',
                'manifest': {'game': 'don', 'adapter': 'don-test-v1', 'pads': pads, 'disc_sha256': 'c'*64},
                'players': [{'participant_id': s+10, 'member': s+1, 'slot': s,
                             'pad': pads[s], 'address': f'10.147.0.{s+1}', 'port': 47400,
                             'name': f'P{s+1}', 'online': True, 'ready': True} for s in range(4)]}

    def test_factory_assigns_host_and_guests_from_api(self):
        snap = self.snapshot()
        with patch('multiplayer_client.Node') as factory:
            make_node(snap, FourPadCore(0))
            self.assertTrue(factory.call_args.kwargs['roster_locked'])
            self.assertEqual(factory.return_value.add_expected_peer.call_count, 3)
            snap['slot'] = 3
            make_node(snap, FourPadCore(3))
            self.assertEqual(factory.call_args.args[1:3], (4, 3))
            self.assertEqual(factory.call_args.kwargs['host'], ('10.147.0.1', 47400))

    def test_rejects_legacy_two_pad_core_and_incomplete_rosters(self):
        with self.assertRaisesRegex(ValueError, 'adaptador'):
            make_node(self.snapshot(), object())
        for mutate in (lambda s: s.update(ready=False),
                       lambda s: s['players'].pop(),
                       lambda s: s['players'][3].update(member=2),
                       lambda s: s['players'][3].update(ready=False),
                       lambda s: s['players'][3].update(address='127.0.0.1')):
            snap = copy.deepcopy(self.snapshot())
            mutate(snap)
            with self.assertRaises(ValueError):
                make_node(snap, FourPadCore(0))

    def test_rejects_input_only_adapter_and_state_with_other_player_count(self):
        core = FourPadCore(0)
        core.simulation_hashes = False
        with self.assertRaisesRegex(ValueError, 'estado del juego'):
            make_node(self.snapshot(), core)
        core.simulation_hashes = True
        core.capacity = 2
        with self.assertRaisesRegex(ValueError, 'cantidad'):
            make_node(self.snapshot(), core)

    def test_client_uses_ticket_and_new_api_paths(self):
        with patch('multiplayer_client.api_call', return_value={}) as call:
            client = RoomClient('http://localhost:8000', 'private-ticket')
            client.request(self.snapshot()['session_epoch'], 'join')
            self.assertEqual(call.call_args.args[1], 'POST')
            self.assertTrue(call.call_args.args[2].endswith('/join/'))
            self.assertEqual(call.call_args.kwargs['token'], 'private-ticket')

    def test_watch_keeps_presence_and_clears_ready_on_interrupt(self):
        with patch('multiplayer_client.api_call', return_value=self.snapshot()) as call, \
                patch('multiplayer_client.time.sleep', side_effect=KeyboardInterrupt), \
                patch('builtins.print'):
            watch(RoomClient('http://localhost:8000', 'private-ticket'), self.snapshot()['session_epoch'],
                  self.snapshot()['manifest'], '10.147.0.1', ready=True)
            self.assertTrue(call.call_args_list[0].args[3]['ready'])
            self.assertFalse(call.call_args_list[1].args[3]['ready'])

    def test_four_nodes_agree_with_loss_and_reordering(self):
        network, cores, nodes = {}, [FourPadCore(s) for s in range(4)], []
        for s, core in enumerate(cores):
            sock = MemorySocket(network, (f'10.147.0.{s+1}', 47400))
            node = Node(core, s+1, s, 47400, [0, 1, 2, 3], sock=sock, delay=3,
                        host=None if s == 0 else ('10.147.0.1', 47400),
                        roster_locked=True, generic=True)
            node.sel_sync = False
            nodes.append(node)
        for s in range(1, 4):
            nodes[0].add_expected_peer(s+1, s, (f'10.147.0.{s+1}', 47400))
        def readable(readers, *args):
            return [s for s in readers if s.queue], [], []
        with patch('node.select.select', side_effect=readable):
            for tick in range(1000):
                for node in nodes:
                    node.last_hello = 0
                    node.pump()
                for core in cores:
                    core.step()
                if tick % 9 == 0:
                    for sock in network.values():
                        if sock.queue:
                            sock.queue.popleft()           # deterministic packet loss
                        sock.queue.reverse()
                if min(core.frame for core in cores) >= 100 and nodes[0].checked >= 90:
                    break
        self.assertGreaterEqual(min(c.frame for c in cores), 100)
        self.assertGreaterEqual(nodes[0].checked, 90)
        for f in range(90):
            self.assertEqual(len({core.history[f] for core in cores}), 1)
        self.assertIsNone(nodes[0].desync)
        for slot in range(4):
            self.assertEqual(cores[0].inputs[slot][5], cores[slot].outputs[2])

    def test_guest_cannot_publish_another_players_input(self):
        sock = MemorySocket({}, ('10.147.0.1', 47400))
        host = Node(FourPadCore(0), 1, 0, 0, [0, 1, 2, 3], sock=sock, roster_locked=True, generic=True)
        peer = host.add_expected_peer(2, 1, ('10.147.0.2', 47400))
        host._on_data(peer, {'acks': [0]*4, 'blocks': [(2, 4, [NEUTRAL])], 'hashes': []})
        self.assertNotIn(4, host.known[2])

    def test_four_nodes_over_real_loopback_udp(self):
        cores, nodes = [FourPadCore(s) for s in range(4)], []
        try:
            host = Node(cores[0], 1, 0, 0, [0, 1, 2, 3], bind='127.0.0.1',
                        roster_locked=True, generic=True)
            nodes.append(host)
            for slot in range(1, 4):
                guest = Node(cores[slot], slot+1, slot, 0, [0, 1, 2, 3],
                             bind='127.0.0.1', host=host.sock.getsockname(),
                             roster_locked=True, generic=True)
                nodes.append(guest)
                host.add_expected_peer(slot+1, slot, guest.sock.getsockname())
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                for node in nodes:
                    node.sel_sync = False
                    node.pump()
                for core in cores:
                    core.step()
                if host.checked >= 90:
                    break
                time.sleep(0.001)
            self.assertGreaterEqual(host.checked, 90)
            self.assertIsNone(host.desync)
            for f in range(90):
                self.assertEqual(len({core.history[f] for core in cores}), 1)
        finally:
            for node in nodes:
                node.close()

    def test_generic_hash_mismatch_is_not_suppressed_by_naruto_scene_hash(self):
        sock = MemorySocket({}, ('10.147.0.1', 47400))
        core = FourPadCore(0)
        core.history[0] = NULL_STATE_HASH
        host = Node(core, 1, 0, 0, [0, 1], sock=sock, generic=True)
        host.add_expected_peer(2, 1, ('10.147.0.2', 47400))
        host.reports[2], host.hash_need[2] = {0: 42}, 1
        host._hash_step()
        self.assertEqual(host.desync, 0)


if __name__ == '__main__':
    unittest.main()
