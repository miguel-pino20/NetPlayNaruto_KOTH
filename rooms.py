"""Room discovery for UN5 netplay on a LAN or a virtual LAN (Radmin VPN, ZeroTier, Hamachi ...).

A host announces its room with a small UDP broadcast every 2 seconds; the launcher listens and lists every room it
hears, with the host's nick, address, delay and whether it holds the same match state as you. A room disappears a few
seconds after its host stops announcing (match over, program closed).

Radmin VPN is a virtual network (26.0.0.0/8) that forwards broadcasts like a real LAN, so the hosts of everybody in
your Radmin network show up by themselves. It works only on a network that forwards broadcasts: over the plain
internet (no VPN) nothing is discovered, type the host's address by hand as before.

Test it without the game, on two PCs of the same network:
    PC 1:   python rooms.py announce --nick Naruto
    PC 2:   python rooms.py listen
PC 2 must print the room. If it does not, the network (or a firewall: allow python on UDP 47401) blocks broadcasts.

Everything received here comes from the network, so it is validated field by field and never trusted: sizes are
capped, types are checked, nicks are reduced to printable ASCII.
"""
import argparse
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
import json
import re
import socket
import sys
import time

DISCOVERY_PORT = 47401
ZEROTIER_DISCOVERY_PORT = 47403
ZEROTIER_GAME_PORT = 47400
ZEROTIER_GROUP = '239.255.47.43'
MAGIC = b'UN5R1'                    # 'UN5 Room', protocol version 1
MAX_PACKET = 512
ANNOUNCE_EVERY = 2.0                # seconds between two announcements of the same room
ROOM_TTL = 7.0                      # seconds without an announcement before a room is dropped
MAX_ROOMS = 64                      # a flood of fake rooms can not grow the list beyond this
STATUSES = ('waiting', 'playing')
_TAG_RE = re.compile(r'^[0-9a-f]{16}$')
_ROOM_SESSION_RE = re.compile(r'^[0-9a-f]{32}$')
_DISCOVERY_ADDRESS_POOLS = tuple(map(IPv4Network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10')))
DJANGO_DISCOVERY_PATH = '/api/netplay/casual/discovery/'


def discovery_subnet(value):
    try:
        address = IPv4Address(value)
    except ValueError:
        return None
    if any(address in pool for pool in _DISCOVERY_ADDRESS_POOLS):
        network = IPv4Interface(f'{address}/24').network
        if address not in (network.network_address, network.broadcast_address):
            return network
    return None


def django_rooms(url, session, local_address, port):
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlencode
    from discord_auth import AccountError, api_call
    from statesync import StateError, advertised_room

    subnet = discovery_subnet(local_address)
    if not session or not subnet:
        return []
    try:
        response = api_call(url, 'GET', DJANGO_DISCOVERY_PATH + '?' + urlencode({'address': local_address}),
                            extra_headers={'X-Netplay-Session': session}, timeout=3, follow_redirects=False)
    except AccountError:
        return []  # Older Django deployments can still use the LAN listener.

    def confirm(candidate):
        address, key = candidate.get('address'), candidate.get('session')
        if (address == local_address or discovery_subnet(address) != subnet or not isinstance(key, str)
                or not _ROOM_SESSION_RE.fullmatch(key) or not uses_interface(address, local_address)):
            return None
        try:
            payload = advertised_room(address, port, local_address, key, MAX_PACKET)
        except (OSError, StateError):
            return None
        room = parse_room(payload, (address, port))
        return room if room and room.get('game') and room['port'] == port and room['status'] == 'waiting' else None

    candidates = response.get('rooms', []) if isinstance(response, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        return [room for room in pool.map(confirm, (row for row in candidates[:32] if isinstance(row, dict))) if room]


class DjangoRoomPublisher:
    """Publishes a short lease while the game's host is waiting, outside the frame loop."""

    def __init__(self, url, token, room_id, address, state_server, packet):
        from threading import Event, Thread

        self.url, self.token = url, token
        self.room_id, self.address = room_id, address
        self.state_server = state_server
        self.state_server.room_advertisement = bytes.fromhex(room_id), packet
        self.stopped = Event()
        self.worker = Thread(target=self._run, name='room-discovery', daemon=True)
        self.worker.start()

    def _run(self):
        from discord_auth import AccountError, api_call

        def update(waiting):
            api_call(self.url, 'POST', DJANGO_DISCOVERY_PATH,
                     {'session': self.room_id, 'address': self.address, 'waiting': waiting},
                     extra_headers={'X-Netplay-Session': self.token}, timeout=3, follow_redirects=False)

        published = False
        while not self.stopped.is_set():
            try:
                update(True)
                published = True
            except AccountError:
                pass  # Registration may still be in flight, or the deployment may predate the endpoint.
            self.stopped.wait(5)
        if published:
            try:
                update(False)
            except AccountError:
                pass  # The lease also expires on the server.

    def close(self):
        self.state_server.room_advertisement = None
        self.stopped.set()


def clean_nick(value, limit=15):
    """Printable ASCII only, no '<' or '>' (they start font tags in the game), at most `limit` characters."""
    value = str(value or '')
    return ''.join(ch if 32 <= ord(ch) <= 126 and ch not in '<>' else '?' for ch in value).strip()[:limit]


# ---- packets ----------------------------------------------------------------------------------------------------------
def encode_room(nick, port, delay, tag, status='waiting', game=None, *, guest='', ping=None):
    body = {'n': clean_nick(nick) or 'Player', 'p': int(port), 'd': int(delay), 't': str(tag), 's': status}
    if game is not None:
        body['g'] = game
    if status == 'playing' and guest:
        body['guest'] = clean_nick(guest)
    if status == 'playing' and ping is not None:
        body['ping'] = ping
    return MAGIC + json.dumps(body, separators=(',', ':')).encode('ascii')


def _int_in(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        return None
    return value


def parse_room(data, addr):
    """The room announced by `data` (received from `addr`), or None when the packet is not a valid announcement.
    The host's address is the packet's source address, never a value inside the packet."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_PACKET or not data.startswith(MAGIC):
        return None
    try:
        body = json.loads(bytes(data[len(MAGIC):]).decode('ascii'))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    nick, tag, status = body.get('n'), body.get('t'), body.get('s')
    port, delay = _int_in(body.get('p'), 1, 65535), _int_in(body.get('d'), 0, 30)
    if (not isinstance(nick, str) or not isinstance(tag, str) or not _TAG_RE.match(tag) or status not in STATUSES
            or port is None or delay is None or not isinstance(addr, tuple) or not isinstance(addr[0], str)):
        return None
    room = {'nick': clean_nick(nick) or 'Player', 'ip': addr[0], 'port': port, 'delay': delay, 'tag': tag,
            'status': status}
    if body.get('g') in ('un5', 'un6'):
        room['game'] = body['g']
    if status == 'playing':
        guest = body.get('guest')
        if isinstance(guest, str) and clean_nick(guest):
            room['players'] = {'guest': {'nick': clean_nick(guest)}}
        ping = _int_in(body.get('ping'), 0, 65535)
        if ping is not None:
            room['ping'] = ping
    return room


def zerotier_targets(address):
    from zerotier_networks import discover

    targets = [ZEROTIER_GROUP]
    choices, _status = discover()
    for choice in choices:
        if choice['address'] != address or 'prefix' not in choice:
            continue
        network = IPv4Interface(f"{address}/{choice['prefix']}").network
        if 0 < network.prefixlen < 31:
            broadcast = str(network.broadcast_address)
            if uses_interface(broadcast, address) and broadcast not in targets:
                targets.append(broadcast)
    return targets


def uses_interface(peer, local_address):
    """Ask the OS which interface a direct connection would use, without sending data."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            probe.connect((peer, ZEROTIER_DISCOVERY_PORT))
            return probe.getsockname()[0] == local_address
    except OSError:
        return False


# ---- addresses --------------------------------------------------------------------------------------------------------
def local_ipv4s():
    """This PC's IPv4 addresses (the Radmin one starts with 26.), without loopback and link-local."""
    found = []
    try:
        found += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('10.255.255.255', 1))                 # no packet is sent: it only picks the default interface
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    out = []
    for ip in found:
        if ip not in out and not ip.startswith(('127.', '169.254.', '0.')):
            out.append(ip)
    return out


def radmin_ip(ips=None):
    return next((ip for ip in (local_ipv4s() if ips is None else ips) if ip.startswith('26.')), None)


def broadcast_targets(ip):
    """Where to send a broadcast from the interface with address `ip`. Radmin VPN is 26.0.0.0/8; any other network is
    assumed to be a /24 (the usual home LAN)."""
    parts = ip.split('.')
    if len(parts) != 4:
        return ['255.255.255.255']
    first = '26.255.255.255' if parts[0] == '26' else '.'.join(parts[:3] + ['255'])
    return [first, '255.255.255.255']


# ---- host side ----------------------------------------------------------------------------------------------------------
class RoomAnnouncer:
    """Call tick(status) from the host's main loop: it announces at most once per `interval`, never blocks and never
    raises. One socket per local interface, bound to that interface, so the broadcast leaves through the right
    network (Radmin included) instead of only the default one."""

    def __init__(self, nick, port, delay, tag, interval=ANNOUNCE_EVERY, dest_port=DISCOVERY_PORT, targets=None,
                 *, bind_ip=None, game=None):
        self.nick, self.port, self.delay, self.tag = clean_nick(nick) or 'Player', int(port), int(delay), str(tag)
        self.interval, self.dest_port = interval, dest_port
        self.routes, self.ips, self.sent, self._last = [], [], 0, None
        self.game = game
        if game and bind_ip:
            self.dest_port = ZEROTIER_DISCOVERY_PORT
            sock = self._socket(bind_ip, multicast=True)
            if sock:
                self.routes.append((sock, zerotier_targets(bind_ip)))
                self.ips.append(bind_ip)
        elif targets is not None:                              # tests: explicit destinations, any interface
            sock = self._socket(None)
            if sock:
                self.routes.append((sock, list(targets)))
        else:
            for ip in local_ipv4s():
                sock = self._socket(ip)
                if sock:
                    self.routes.append((sock, broadcast_targets(ip)))
                    self.ips.append(ip)

    @staticmethod
    def _socket(bind_ip, multicast=False):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if multicast:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(bind_ip))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            if bind_ip:
                sock.bind((bind_ip, 0))
            sock.setblocking(False)
            return sock
        except OSError:
            if sock is not None:
                sock.close()
            return None

    def tick(self, status='waiting', now=None, *, guest='', ping=None):
        now = time.monotonic() if now is None else now
        if self._last is not None and now - self._last < self.interval:
            return False
        self._last = now
        packet = encode_room(self.nick, self.port, self.delay, self.tag, status, self.game, guest=guest, ping=ping)
        for sock, targets in self.routes:
            for target in targets:
                try:
                    sock.sendto(packet, (target, self.dest_port))
                    self.sent += 1
                except OSError:
                    pass
        return True

    def close(self):
        for sock, _ in self.routes:
            try:
                sock.close()
            except OSError:
                pass
        self.routes = []


# ---- guest side ---------------------------------------------------------------------------------------------------------
class RoomListener:
    """poll() (non-blocking, call it every few hundred ms) returns the rooms heard recently, sorted by nick."""

    def __init__(self, port=DISCOVERY_PORT, bind='0.0.0.0', ttl=ROOM_TTL, *, zerotier_address=None):
        self.zerotier_address = zerotier_address
        self.port = ZEROTIER_DISCOVERY_PORT if zerotier_address else port
        self.ttl, self.error, self.rooms, self.sock = ttl, None, {}, None
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # two launchers on one PC may both listen
            sock.bind((bind, self.port))
            if zerotier_address:
                membership = socket.inet_aton(ZEROTIER_GROUP) + socket.inet_aton(zerotier_address)
                try:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
                except OSError:
                    # Directed broadcast can still arrive on the discovery port.
                    pass
            sock.setblocking(False)
            self.sock = sock
        except OSError as exc:
            if sock is not None:
                sock.close()
            self.error = str(exc)

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        if self.sock is not None:
            for _ in range(200):                                # bounded: a flood can not freeze the window
                try:
                    data, addr = self.sock.recvfrom(1024)
                except (BlockingIOError, InterruptedError):
                    break
                except ConnectionResetError:                    # Windows reports an old ICMP error here: not fatal
                    continue
                except OSError:
                    break
                room = parse_room(data, addr)
                if room is None:
                    continue
                key = (room['ip'], room['port'])
                if key not in self.rooms and len(self.rooms) >= MAX_ROOMS:
                    continue
                room['seen'] = now
                self.rooms[key] = room
        for key in [k for k, r in self.rooms.items() if now - r['seen'] > self.ttl]:
            del self.rooms[key]
        return sorted(self.rooms.values(), key=lambda r: (r['nick'].lower(), r['ip'], r['port']))

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


# ---- command line: test the discovery without the game --------------------------------------------------------------------
def _cmd_listen(args):
    ips = local_ipv4s()
    print(f'this PC: {", ".join(ips) or "no address found"}' + (f'   (Radmin: {radmin_ip(ips)})' if radmin_ip(ips) else ''))
    listener = RoomListener()
    if listener.error:
        print(f'cannot listen on UDP {DISCOVERY_PORT}: {listener.error}')
        return 1
    print(f'listening on UDP {DISCOVERY_PORT} ... Ctrl+C to stop')
    shown, end = {}, (time.monotonic() + args.seconds) if args.seconds else None
    try:
        while end is None or time.monotonic() < end:
            current = {(r['ip'], r['port']): r for r in listener.poll()}
            for key, r in current.items():
                if key not in shown:
                    print(f"+ {r['nick']:15s} {key[0]}:{key[1]}  delay {r['delay']}  {r['status']}  state {r['tag']}")
            for key, r in shown.items():
                if key not in current:
                    print(f"- {r['nick']} {key[0]}:{key[1]} is gone")
            shown = current
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        listener.close()
    return 0


def _cmd_announce(args):
    announcer = RoomAnnouncer(args.nick, args.port, args.delay, args.tag, interval=1.0)
    if not announcer.routes:
        print('no network interface could be used to announce')
        return 1
    for (sock, targets), ip in zip(announcer.routes, announcer.ips):
        print(f'announcing from {ip} to {", ".join(targets)}  (UDP {DISCOVERY_PORT})')
    print('Ctrl+C to stop')
    try:
        while True:
            announcer.tick('waiting')
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        announcer.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('listen', help='print the rooms heard on this network')
    p.add_argument('--seconds', type=float, default=0, help='stop after this long (0 = until Ctrl+C)')
    p = sub.add_parser('announce', help='announce a test room')
    p.add_argument('--nick', default='Tester')
    p.add_argument('--port', type=int, default=47400)
    p.add_argument('--delay', type=int, default=3)
    p.add_argument('--tag', default='0' * 16, help='16 hex digits (the match state tag)')
    args = ap.parse_args(argv)
    return _cmd_listen(args) if args.cmd == 'listen' else _cmd_announce(args)


if __name__ == '__main__':
    sys.exit(main())
