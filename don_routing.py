"""Authenticated UDP bridges for D.O.N; logical player identities stay fixed.

Only the room roster can relay. Routes carry their complete, loop-free path;
measured edge costs expire and route changes require a meaningful improvement.
This socket implements the subset used by Node, without changing Naruto's wire.
"""
import hashlib
import hmac
import itertools
import json
import math
import secrets
import socket
import statistics
import struct
import time
from collections import deque

PROTOCOL = 'don-bridge-v1'
HEADER = struct.Struct('<4s8sBBBBH')
DATA, PING, PONG, GRAPH = range(4)
TTL = 10


class BridgeSocket:
    def __init__(self, snapshot):
        self.slot = snapshot['slot']
        self.addresses = {p['slot']: (p['address'], p['port']) for p in snapshot['players']}
        self.by_address = {a: s for s, a in self.addresses.items()}
        identity = json.dumps([PROTOCOL, snapshot['id'], snapshot['session_epoch'], snapshot['manifest']],
                              sort_keys=True, separators=(',', ':')).encode()
        self.key = hashlib.sha256(identity).digest()
        self.tag = hashlib.sha256(self.key).digest()[:8]
        self.raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.raw.bind(self.addresses[self.slot])
            self.raw.setblocking(False)
        except BaseException:
            self.raw.close()
            raise
        self.pending, self.samples, self.edges, self.sequences, self.routes = {}, {}, {}, {}, {}
        self.sequence, self.next_probe, self.next_graph = 0, 0, 0

    def fileno(self):
        return self.raw.fileno()

    def setblocking(self, value):
        self.raw.setblocking(value)

    def getsockname(self):
        return self.raw.getsockname()

    def close(self):
        self.raw.close()

    def _send(self, kind, path, cursor, payload):
        packet = HEADER.pack(b'DNR1', self.tag, kind, len(path), cursor, 0, len(payload)) + bytes(path) + payload
        packet += hmac.digest(self.key, packet, 'sha256')[:16]
        return self.raw.sendto(packet, self.addresses[path[cursor]])

    def _cost(self, path, now):
        edges = [self.edges.get((a, b)) for a, b in zip(path, path[1:])]
        return sum(e[1] for e in edges) if all(e and now-e[2] < TTL for e in edges) else math.inf

    def route(self, target):
        now = time.monotonic()
        middle = [s for s in self.addresses if s not in (self.slot, target)]
        paths = [(self.slot, *p, target) for n in range(len(middle)+1)
                 for p in itertools.permutations(middle, n)]
        best = min(paths, key=lambda p: (self._cost(p, now), len(p)))
        old, changed = self.routes.get(target, ((self.slot, target), 0))
        old_cost, new_cost = self._cost(old, now), self._cost(best, now)
        if best != old and (not math.isfinite(old_cost) or
                (now-changed >= 2 and new_cost + max(3, old_cost*.05) < old_cost)):
            old, changed = best, now
        self.routes[target] = old, changed
        return old

    def sendto(self, payload, address):
        target = self.by_address.get(address)
        if target is None or target == self.slot or len(payload) > 1400:
            raise OSError('Destino o tamaño UDP fuera de la sala D.O.N.')
        self._send(DATA, self.route(target), 1, payload)
        return len(payload)

    def tick(self):
        """Send probes without hiding received packets from Node's select()."""
        now = time.monotonic()
        self.pending = {n: p for n, p in self.pending.items() if now-p[1] < 3}
        if now >= self.next_probe:
            self.next_probe = now+1
            for target in self.addresses:
                if target == self.slot:
                    continue
                nonce = secrets.token_bytes(8)
                self.sequence += 1
                self.pending[nonce] = target, now, self.sequence
                self._control(PING, target, nonce)
        if now >= self.next_graph:
            self.next_graph = now+1
            rows = [[a, b, seq, rtt, max(0, now-seen)] for (a, b), (seq, rtt, seen) in self.edges.items()
                    if now-seen < TTL]
            payload = json.dumps(rows, separators=(',', ':')).encode()
            for target in self.addresses:
                if target != self.slot:
                    self._control(GRAPH, target, payload)

    def _control(self, kind, target, payload):
        try:
            self._send(kind, (self.slot, target), 1, payload)
        except OSError:
            pass  # Unreachable edges must not prevent another player relaying.

    def _receive_control(self, kind, source, payload):
        now = time.monotonic()
        if kind == PING and len(payload) == 8:
            self._control(PONG, source, payload)
        elif kind == PONG:
            pending = self.pending.pop(payload, None)
            if pending and pending[0] == source:
                _, sent, seq = pending
                edge = self.slot, source
                if seq > self.sequences.get(edge, -1):
                    samples = self.samples.setdefault(source, deque(maxlen=5))
                    samples.append((now-sent)*1000)
                    self.edges[edge] = seq, statistics.median(samples), now
                    self.sequences[edge] = seq
        elif kind == GRAPH:
            try:
                rows = json.loads(payload)
                if not isinstance(rows, list) or len(rows) > 12:
                    return
                for a, b, seq, rtt, age in rows:
                    if (type(a) is not int or type(b) is not int or a == self.slot or a == b or
                            a not in self.addresses or b not in self.addresses or type(seq) is not int or seq < 0 or
                            type(rtt) not in (int, float) or not math.isfinite(rtt) or not 0 <= rtt <= 10000 or
                            type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age < TTL):
                        continue
                    edge = a, b
                    if seq > self.sequences.get(edge, -1):
                        self.sequences[edge] = seq
                        self.edges[edge] = seq, rtt, now-age
            except (ValueError, TypeError):
                return

    def recvfrom(self, size):
        for _ in range(256):
            packet, address = self.raw.recvfrom(2048)
            if len(packet) < HEADER.size+18 or len(packet) > 1500:
                continue
            magic, tag, kind, count, cursor, reserved, length = HEADER.unpack_from(packet)
            if (magic != b'DNR1' or tag != self.tag or reserved or kind not in (DATA, PING, PONG, GRAPH) or
                    not 2 <= count <= len(self.addresses) or not 1 <= cursor < count or
                    len(packet) != HEADER.size+count+length+16 or
                    not hmac.compare_digest(packet[-16:], hmac.digest(self.key, packet[:-16], 'sha256')[:16])):
                continue
            path = tuple(packet[HEADER.size:HEADER.size+count])
            if (len(set(path)) != count or any(s not in self.addresses for s in path) or
                    path[cursor] != self.slot or address != self.addresses[path[cursor-1]]):
                continue
            payload = packet[HEADER.size+count:-16]
            if kind != DATA:
                if count == 2:
                    self._receive_control(kind, path[0], payload)
            elif cursor < count-1:
                try:
                    self._send(kind, path, cursor+1, payload)
                except OSError:
                    pass
            else:
                return payload[:size], self.addresses[path[0]]
        raise BlockingIOError

    def route_stats(self):
        now = time.monotonic()
        result = {}
        for target in self.addresses:
            if target == self.slot:
                continue
            path = self.route(target)
            cost = self._cost(path, now)
            result[target] = {'path': list(path), 'rtt': round(cost, 1) if math.isfinite(cost) else None}
        return result
