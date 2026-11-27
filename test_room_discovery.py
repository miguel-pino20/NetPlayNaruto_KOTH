from ipaddress import IPv4Network
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from rooms import DjangoRoomPublisher, django_rooms, encode_room
from statesync import StateServer, advertised_tag, file_tag


class DjangoRoomDiscoveryTests(TestCase):
    def test_only_verified_waiting_room_appears_without_multicast(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.p2s'
            state.write_bytes(b'test state')
            host, client = '127.0.0.2', '127.0.0.1'
            tag = file_tag(state)
            server = StateServer(state, 0, bind=host, metadata_only=True)
            self.addCleanup(server.close)
            port = server.sock.getsockname()[1]
            room_key = 'a' * 32
            packet = encode_room('P1', port, 3, tag, game='un6')
            response = {'rooms': [
                {'address': host, 'session': 'b' * 32},
                {'address': '192.168.196.2', 'session': room_key},
                {'address': host, 'session': room_key},
            ]}

            def api_call(_url, method, _path, *args, **kwargs):
                self.assertFalse(kwargs['follow_redirects'])
                return response if method == 'GET' else {}

            subnet = IPv4Network('127.0.0.0/24')
            with patch('rooms.discovery_subnet', side_effect=lambda ip: subnet if ip in (host, client) else None), patch(
                    'discord_auth.api_call', side_effect=api_call):
                publisher = DjangoRoomPublisher('https://example.com', 'host-token', room_key, host, server, packet)
                try:
                    rooms = django_rooms('https://example.com', 'guest-token', client, port)
                    self.assertEqual([(room['ip'], room['game']) for room in rooms], [(host, 'un6')])
                    self.assertEqual(advertised_tag(host, port), tag)
                finally:
                    publisher.close()
                    publisher.worker.join(timeout=2)
                self.assertEqual(django_rooms('https://example.com', 'guest-token', client, port), [])
