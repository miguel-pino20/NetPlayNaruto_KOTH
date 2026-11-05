import argparse
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import hill


class HillTests(unittest.TestCase):
    def setUp(self):
        prepare = patch('hill.prepare_waiting', return_value=True)
        release = patch('hill.release_game')
        self.prepare = prepare.start()
        self.release = release.start()
        self.addCleanup(prepare.stop)
        self.addCleanup(release.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / 'state').write_bytes(b'match state')
        (root / 'symbols').write_text('{}')
        self.args = argparse.Namespace(api_url='http://localhost:8000', address='10.147.0.2', game='un6',
            port=47400, delay=3, state=str(root/'state'), symbols=str(root/'symbols'), state_dir=str(root),
            load_slot=9, pine_slot=28011, nick='Player', stop_file=str(root/'stop'))

    def snapshot(self, round_id='one', role='host', ready=True, status='running'):
        return dict(round_id=round_id, role=role, ready=ready, status=status, reason='', transport='relay',
                    queue=[dict(id=1, name='A', points=0)],
                    host=dict(address='10.147.0.1', port=47400, delay=4, relay_room='main-room'))

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket', 'NP_SERVER': 'old-relay'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_rotation_stops_previous_session_and_changes_role(self, sync, popen, sleep):
        sync.side_effect = [self.snapshot(), self.snapshot('two', 'guest', False),
                            self.snapshot('two', 'guest'), self.snapshot(status='finished'), {}]
        popen.side_effect = [Mock(poll=Mock(return_value=None)), Mock(poll=Mock(return_value=None))]
        self.assertEqual(hill.run(self.args), 0)
        self.assertEqual(popen.call_count, 2)
        host, guest = [c.args[0] for c in popen.call_args_list]
        self.assertIn('host', host)
        self.assertIn('--no-share-state', host)
        self.assertIn('guest', guest)
        self.assertIn('main-room', guest)
        self.assertNotIn('--connect', guest)
        self.assertEqual(host[host.index('--server')+1], '137.131.158.54:47500')
        self.assertIn('--relay-only', host)
        self.assertIn('--relay-only', guest)
        self.assertIn('--parent-stop-file', host)
        self.assertNotIn('private-ticket', ' '.join(host))
        self.assertNotIn('UN5_HILL_TICKET', popen.call_args.kwargs['env'])

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_failed_session_does_not_restart_same_round(self, sync, popen, sleep):
        sync.side_effect = [self.snapshot(), self.snapshot(), self.snapshot(status='finished'), {}]
        popen.return_value.poll.return_value = 2
        self.assertEqual(hill.run(self.args), 0)
        self.assertEqual(popen.call_count, 1)
        self.assertFalse(sync.call_args_list[1].args[2]['available'])

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_stop_removes_presence_and_stops_child(self, sync, popen, sleep):
        sync.return_value = self.snapshot()
        popen.return_value.poll.return_value = None
        sleep.side_effect = lambda _: Path(self.args.stop_file).touch()
        self.assertEqual(hill.run(self.args), 0)
        popen.return_value.wait.assert_called()
        self.assertTrue(sync.call_args.args[2]['offline'])

    def test_url_rejects_query_credentials_and_non_http(self):
        for url in ('file:///tmp/x', 'https://user:password@example.com', 'https://example.com?ticket=secret'):
            with self.assertRaises(ValueError):
                hill.validate_url(url)

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_waiting_player_loads_state_before_being_announced_ready(self, sync, popen, sleep):
        order = []
        self.prepare.side_effect = lambda args: order.append('load') or True
        def heartbeat(*args):
            order.append('sync')
            if len(order) == 2:
                return self.snapshot(role=None, ready=False)
            return self.snapshot(role=None, ready=False, status='finished')
        sync.side_effect = heartbeat
        self.assertEqual(hill.run(self.args), 0)
        self.assertEqual(order[:2], ['load', 'sync'])
        popen.assert_not_called()
        self.release.assert_called_once_with(self.args)

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.sync')
    def test_failed_load_never_announces_player_and_releases_game(self, sync):
        self.prepare.return_value = False
        with self.assertRaises(hill.HillError):
            hill.run(self.args)
        sync.assert_not_called()
        self.release.assert_called_once_with(self.args)

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_spectator_is_promoted_to_player_automatically(self, sync, popen, sleep):
        watch = self.snapshot(role='spectator')
        watch['host']['spectator_port'] = 47401
        watch['spectator_key'] = 'private-view-key'
        sync.side_effect = [watch, self.snapshot('two', 'guest'), self.snapshot(status='finished'), {}]
        first = Mock(poll=Mock(return_value=None))
        second = Mock(poll=Mock(return_value=None))
        popen.side_effect = [first, second]
        self.assertEqual(hill.run(self.args), 0)
        self.assertEqual(popen.call_count, 2)
        commands = [call.args[0] for call in popen.call_args_list]
        self.assertIn('watch', commands[0])
        self.assertIn('10.147.0.1:47401', commands[0])
        self.assertIn('guest', commands[1])
        self.assertNotIn('private-view-key', ' '.join(commands[0]))
        self.assertEqual(popen.call_args_list[0].kwargs['env']['UN5_SPECTATOR_KEY'], 'private-view-key')
        first.wait.assert_called()

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_failed_spectator_remains_available_as_player(self, sync, popen, sleep):
        watch = self.snapshot(role='spectator')
        watch['host']['spectator_port'] = 47401
        watch['spectator_key'] = 'key'
        sync.side_effect = [watch, watch, self.snapshot('two', 'guest'), self.snapshot(status='finished'), {}]
        popen.side_effect = [Mock(poll=Mock(return_value=1)), Mock(poll=Mock(return_value=None))]
        self.assertEqual(hill.run(self.args), 0)
        self.assertTrue(sync.call_args_list[1].args[2]['available'])
        self.assertEqual(popen.call_count, 2)

    def test_host_opens_spectator_port_without_exposing_key_in_command(self):
        snapshot = self.snapshot()
        snapshot['host']['spectator_port'] = 47401
        snapshot['spectator_key'] = 'private-view-key'
        command = hill.match_command(self.args, snapshot, '/tmp/stop')
        self.assertEqual(command[command.index('--spectator-port')+1], '47401')
        self.assertNotIn('private-view-key', command)

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_guest_waits_for_room_id_from_principal_server(self, sync, popen, sleep):
        waiting = self.snapshot(role='guest')
        waiting['host']['relay_room'] = ''
        sync.side_effect = [waiting, self.snapshot(role='guest'), self.snapshot(status='finished'), {}]
        popen.return_value.poll.return_value = None
        self.assertEqual(hill.run(self.args), 0)
        self.assertEqual(popen.call_count, 1)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index('--room')+1], 'main-room')
        self.assertNotIn('--connect', command)

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.time.sleep')
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_host_announces_room_and_real_auto_delay_to_django(self, sync, popen, sleep):
        sync.side_effect = [self.snapshot(), self.snapshot(), self.snapshot(status='finished'), {}]
        def start(command, **kwargs):
            path = Path(command[command.index('--room-file')+1])
            path.write_text('{"room_id":"actual-room","delay":7}')
            return Mock(poll=Mock(return_value=None))
        popen.side_effect = start
        self.assertEqual(hill.run(self.args), 0)
        announced = sync.call_args_list[1].args[2]
        self.assertEqual(announced['room_id'], 'actual-room')
        self.assertEqual(announced['room_round'], 'one')
        self.assertEqual(announced['delay'], 7)

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.subprocess.Popen')
    @patch('hill.sync')
    def test_outdated_django_never_falls_back_to_direct_fight(self, sync, popen):
        old = self.snapshot()
        old.pop('transport')
        sync.return_value = old
        with self.assertRaises(hill.HillError):
            hill.run(self.args)
        popen.assert_not_called()

    @patch.dict(os.environ, {'UN5_NETPLAY_SESSION': 'sample-account-session'})
    def test_online_host_reports_principal_room_without_saving_relay_token(self):
        import json
        import netplay
        import netlink
        args = argparse.Namespace(server=netlink.DEFAULT_SERVER, api_url=netlink.DEFAULT_API_URL,
                                  port=47400, delay=0, relay_only=True, symbols=self.args.symbols,
                                  room_file=str(Path(self.directory.name)/'room.json'))
        api = Mock()
        api.create_room.return_value = {'id': 'principal-room', 'token': '0011223344556677'}
        with patch('netplay.netlink.Api', return_value=api), patch('netplay.netlink.resolve', return_value=('127.0.0.1', 47500)), \
             patch('netplay.netlink.open_socket'), patch('netplay.netlink.whoami', return_value=('192.0.2.1', 47400)), \
             patch('netplay.auto_delay', return_value=7), patch('netplay.netlink.RoomPoller'), \
             patch('netplay.node_mod.Node') as make_node, patch('discord_auth.api_call') as auth:
            netplay.online_open(args, Mock(), True, 'a'*16, 'Host')
        announced = json.loads(Path(args.room_file).read_text())
        self.assertEqual(announced, {'room_id': 'principal-room', 'delay': 7})
        self.assertTrue(make_node.call_args.kwargs['relay_only'])
        self.assertEqual(api.create_room.call_args.args[-1], [])
        self.assertEqual(auth.call_args.args[2], '/presence')

    @patch.dict(os.environ, {'UN5_NETPLAY_SESSION': 'sample-account-session'})
    def test_online_guest_uses_principal_permission_and_relay(self):
        import netplay
        import netlink
        args = argparse.Namespace(server=netlink.DEFAULT_SERVER, api_url=netlink.DEFAULT_API_URL,
                                  bind_port=0, delay=3, relay_only=True, room='principal-room')
        api = Mock()
        api.join_room.return_value = {'tag': 'a'*16, 'delay': 7, 'token': '0011223344556677',
                                      'host': {'addr': ['192.0.2.1', 47400], 'nick': 'Host'}}
        with patch('netplay.netlink.Api', return_value=api), patch('netplay.netlink.resolve', return_value=('127.0.0.1', 47500)), \
             patch('netplay.netlink.open_socket'), patch('netplay.netlink.whoami', return_value=('192.0.2.2', 47400)), \
             patch('netplay.node_mod.Node') as make_node, patch('discord_auth.api_call') as auth:
            netplay.online_open(args, Mock(), False, 'a'*16, 'Guest')
        self.assertEqual(api.join_room.call_args.args[0], 'principal-room')
        self.assertEqual([call.args[2] for call in auth.call_args_list], ['/presence', '/rooms/principal-room/allow'])
        self.assertTrue(make_node.call_args.kwargs['relay_only'])

    @patch.dict(os.environ, {'UN5_HILL_TICKET': 'private-ticket'})
    @patch('hill.sync')
    @patch('builtins.print')
    def test_live_board_messages_exclude_connection_secrets(self, output, sync):
        snapshot = self.snapshot(status='finished')
        snapshot['event'] = {'id': 2, 'name': 'Arena', 'queue': []}
        snapshot['spectator_key'] = 'secret-spectator-key'
        sync.return_value = snapshot
        self.assertEqual(hill.run(self.args), 0)
        lines = [call.args[0] for call in output.call_args_list if call.args and isinstance(call.args[0], str)]
        board = next(line for line in lines if line.startswith('KOTH_STATE '))
        self.assertIn('Arena', board)
        self.assertNotIn('secret-spectator-key', board)
        self.assertNotIn('private-ticket', board)


if __name__ == '__main__':
    unittest.main()
