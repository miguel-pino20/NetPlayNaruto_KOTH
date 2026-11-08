"""Django room coordination and adapter boundary for 2–4 players over ZeroTier.

No game hook is installed by this module. A compatible core must explicitly
advertise max_players and the exact adapter identifier from the room manifest.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import time
from pathlib import Path
from uuid import UUID
from urllib.parse import urlencode

from discord_auth import AccountError, api_call
from hill import validate_url
from node import Node


class RoomClient:
    base_path = '/api/netplay/sessions/'
    def __init__(self, url, ticket):
        self.url, self.ticket = validate_url(url), ticket
        if not ticket:
            raise ValueError('Falta el ticket de participante.')

    def create(self, manifest, capacity, delay=3):
        if capacity not in (2, 3, 4):
            raise ValueError('Selecciona 2, 3 o 4 jugadores.')
        return api_call(self.url, 'POST', self.base_path,
                        {'manifest': manifest, 'capacity': capacity, 'delay': delay}, token=self.ticket)

    def request(self, room_id, action=None, body=None):
        room_id = str(UUID(str(room_id)))
        if action not in (None, 'join', 'sync', 'start', 'leave', 'close'):
            raise ValueError('Acción de sala no válida.')
        path = f'{self.base_path}{room_id}/' + (f'{action}/' if action else '')
        return api_call(self.url, 'POST' if action else 'GET', path,
                        (body or {}) if action else None, token=self.ticket)


class DonRoomClient(RoomClient):
    """Casual rooms authenticated by the launcher account, with no event ticket."""
    api_prefix = '/api/netplay/don/'
    base_path = api_prefix+'sessions/'

    @classmethod
    def authenticate(cls, url, session):
        if not session:
            raise ValueError('Inicia sesión con Discord en el launcher.')
        url = validate_url(url)
        result = api_call(url, 'POST', cls.api_prefix+'access/', {},
                          extra_headers={'X-Netplay-Session': session})
        client = cls(url, result.get('ticket'))
        client.can_publish = result.get('can_publish') is True
        return client

    def create(self, manifest, capacity, delay=3):
        if capacity not in (2, 3, 4):
            raise ValueError('Selecciona 2, 3 o 4 jugadores.')
        return api_call(self.url, 'POST', self.base_path, {'capacity': capacity, 'delay': delay,
                         'network_protocol': 'don-bridge-v1'}, token=self.ticket)

    @staticmethod
    def validate_reference(reference):
        reference = reference.strip()
        try:
            return str(UUID(reference))
        except ValueError:
            pass
        if len(reference) == 6 and reference.isascii() and reference.isalnum():
            return reference.upper()
        parts = reference.split(':')
        try:
            ipaddress.IPv4Address(parts[0])
            if len(parts) > 2 or (len(parts) == 2 and not 1024 <= int(parts[1]) <= 65533):
                raise ValueError
        except ValueError:
            raise ValueError('Introduce el código de 6 caracteres o la IPv4 de ZeroTier del host.') from None
        return reference

    def resolve_room(self, reference):
        reference = self.validate_reference(reference)
        try:
            return {'id': str(UUID(reference))}
        except ValueError:
            return api_call(self.url, 'GET', self.api_prefix+'resolve/?'+urlencode({'q': reference}),
                            token=self.ticket)

    def request(self, room_id, action=None, body=None):
        if action in ('join', 'sync'):
            body = {**(body or {}), 'network_protocol': 'don-bridge-v1'}
        return super().request(room_id, action, body)


class DigimonRoomClient(DonRoomClient):
    api_prefix = '/api/netplay/digimon/'
    base_path = api_prefix+'sessions/'


def watch(client, room_id, manifest, address, port=47400, ready=False):
    """Keep room presence alive. This command never starts emulation."""
    body = {'manifest': manifest, 'address': address, 'port': port, 'ready': ready}
    previous = None
    try:
        while True:
            snapshot = client.request(room_id, 'sync', body)
            rendered = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            if rendered != previous:
                print(json.dumps(snapshot, ensure_ascii=False, indent=2), flush=True)
                previous = rendered
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.request(room_id, 'sync', {**body, 'ready': False})
        except (AccountError, OSError):
            pass  # The server will expire presence if it cannot receive the final heartbeat.


def make_node(snapshot, core, *, experimental_don=False):
    """Create a locked star roster only after the API has started the session.

    The caller must keep heartbeats running and close the node if ready becomes
    false, status changes, or the API is unreachable for its 15-second TTL.
    """
    if snapshot.get('status') != 'running' or not snapshot.get('ready'):
        raise ValueError('La sala no está iniciada y lista.')
    if snapshot.get('transport') != 'zerotier':
        raise ValueError('Esta sesión requiere ZeroTier.')
    capacity, slot = snapshot['capacity'], snapshot['slot']
    if type(capacity) is not int or not 2 <= capacity <= 4 or type(slot) is not int or not 0 <= slot < capacity:
        raise ValueError('Capacidad o puesto inválido.')
    manifest = snapshot['manifest']
    disc = manifest.get('disc_sha256')
    if not isinstance(disc, str) or len(disc) != 64 or any(c not in '0123456789abcdef' for c in disc):
        raise ValueError('La sala no identifica la ISO completa; crea una sala con el manifest actualizado.')
    compatible = {'don': 'don-experimental-input-v1',
                  'digimon-rumble-arena-2': 'digimon-experimental-input-v1'}
    experimental = (experimental_don is True and manifest.get('game') in compatible
                    and manifest.get('adapter') == compatible.get(manifest.get('game'))
                    and getattr(core, 'adapter_id', None) == manifest.get('adapter'))
    if getattr(core, 'simulation_hashes', True) is False and not experimental:
        raise ValueError('Este adaptador solo verifica controles; falta validar el estado del juego para online.')
    if getattr(core, 'capacity', capacity) != capacity:
        raise ValueError('El estado inicial fue preparado para otra cantidad de jugadores.')
    if getattr(core, 'max_players', 2) < capacity or getattr(core, 'adapter_id', None) != manifest['adapter']:
        raise ValueError('Falta un adaptador del juego compatible con esta sala y sus mandos.')
    players = sorted(snapshot['players'], key=lambda p: p['slot'])
    if ([p['slot'] for p in players] != list(range(capacity))
            or [p['member'] for p in players] != list(range(1, capacity + 1))
            or len({p.get('player_id', p.get('participant_id')) for p in players}) != capacity
            or any(p.get('player_id', p.get('participant_id')) is None for p in players)
            or len(manifest['pads']) != capacity):
        raise ValueError('La lista de puestos no es válida.')
    for p in players:
        if (not p.get('online') or not p.get('ready') or p.get('pad') != manifest['pads'][p['slot']]
                or type(p['port']) is not int or not 1024 <= p['port'] <= 65533):
            raise ValueError('Hay un puesto sin preparar o con mandos incompatibles.')
        addr = ipaddress.IPv4Address(p['address'])
        if not addr.is_private or addr.is_unspecified or addr.is_loopback or addr.is_multicast or addr.is_reserved or addr.is_link_local:
            raise ValueError('La sala contiene una dirección de ZeroTier no válida.')
    if len({(p['address'], p['port']) for p in players}) != capacity:
        raise ValueError('Dos puestos usan la misma dirección y puerto.')
    if type(snapshot['delay']) is not int or not 1 <= snapshot['delay'] <= 10:
        raise ValueError('Delay no válido.')
    epoch = str(UUID(snapshot['session_epoch']))
    own, host = players[slot], players[0]
    # Cover every compatibility field, not just the savestate, in the wire tag.
    tag = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
    bridge = None
    if snapshot.get('network_protocol') == 'don-bridge-v1':
        if not experimental:
            raise ValueError('El puente requiere un adaptador experimental conocido.')
        from don_routing import BridgeSocket
        bridge = BridgeSocket(snapshot)
    try:
        node = Node(core, own['member'], slot, own['port'], list(range(capacity)),
                    bind=own['address'], host=None if slot == 0 else (host['address'], host['port']),
                    delay=snapshot['delay'], tag=tag, epoch=epoch, first_capture=1,
                    name=own['name'], roster_locked=True, generic=True, sock=bridge)
    except BaseException:
        if bridge is not None:
            bridge.close()
        raise
    node.bridge = bridge
    node.sel_sync = False                         # Naruto's selection packet is game-specific
    if slot == 0:
        for player in players[1:]:
            node.add_expected_peer(player['member'], player['slot'], (player['address'], player['port']))
    else:
        node.peers[1].slot = 0
        node.peers[1].strict = True
    return node


def main(argv=None):
    parser = argparse.ArgumentParser(description='Salas de 2–4 jugadores (coordinación; no inicia PCSX2).')
    parser.add_argument('--api-url', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    source = create.add_mutually_exclusive_group(required=True)
    source.add_argument('--manifest', type=Path)
    source.add_argument('--profiles', type=Path, help='Seleccionar automáticamente el perfil para --capacity')
    create.add_argument('--capacity', type=int, choices=(2, 3, 4), required=True)
    create.add_argument('--delay', type=int, default=3)
    for action in ('status', 'join', 'sync', 'watch', 'start', 'leave', 'close'):
        cmd = sub.add_parser(action)
        cmd.add_argument('room_id')
        if action in ('sync', 'watch'):
            cmd.add_argument('--manifest', required=True, type=Path)
            cmd.add_argument('--address', required=True)
            cmd.add_argument('--port', type=int, default=47400)
            cmd.add_argument('--ready', action='store_true')
    args = parser.parse_args(argv)
    try:
        client = RoomClient(args.api_url, os.environ.get('UN5_HILL_TICKET', ''))
        if args.command == 'create':
            manifest_path = args.manifest
            if args.profiles:
                from don_profiles import select_profile
                manifest_path = Path(select_profile(args.profiles, args.capacity)['manifest'])
            result = client.create(json.loads(manifest_path.read_text()), args.capacity, args.delay)
        elif args.command == 'watch':
            watch(client, args.room_id, json.loads(args.manifest.read_text()), args.address, args.port, args.ready)
            return 0
        elif args.command == 'sync':
            result = client.request(args.room_id, 'sync', {'manifest': json.loads(args.manifest.read_text()),
                                    'address': args.address, 'port': args.port, 'ready': args.ready})
        else:
            result = client.request(args.room_id, None if args.command == 'status' else args.command)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AccountError, ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
