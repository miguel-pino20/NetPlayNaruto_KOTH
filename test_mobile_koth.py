import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mobile import koth


class MobileKothTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.stop = self.root / 'parent.stop'
        self.state, self.symbols = self.root / 'match.p2s', self.root / 'symbols.json'
        for path in (self.state, self.symbols):
            path.touch()
        self.config = {'directory': directory.name, 'stop_file': str(self.stop), 'url': 'https://events.test',
                       'koth_ticket': 'ticket', 'game': 'un6', 'pine_slot': 28011,
                       'event_name': 'P5', 'address': '10.1.2.4', 'nick': 'Android'}
        self.snapshot = {'round_id': 'round', 'session_epoch': 'epoch', 'status': 'running', 'ready': True,
                         'host': {'address': '10.1.2.3', 'port': 47400, 'spectator_port': 47401, 'delay': 3},
                         'guest': {'address': '10.1.2.4'}, 'spectator_key': 'key', 'transport': 'zerotier'}

    @patch('mobile.koth.play', return_value=0)
    def test_role_launch_passes_shared_round_and_endpoint(self, play):
        for role, command, expected in (
            ('host', 'host', ['--expect-guest-ip', '10.1.2.4']),
            ('guest', 'guest', ['--connect', '10.1.2.3:47400']),
            ('spectator', 'watch', ['--connect', '10.1.2.3:47401']),
        ):
            with self.subTest(role=role):
                snapshot = {**self.snapshot, 'role': role}
                koth.play_round(self.config, snapshot, self.state, self.symbols, self.root / 'round.stop')
                argv = play.call_args.args[0]
                self.assertEqual(argv[8], command)
                self.assertEqual(argv[argv.index('--session-epoch') + 1], 'epoch')
                self.assertEqual(argv[argv.index(expected[0]):][:2], expected)
                self.assertEqual('--preloaded-state' in argv, role == 'spectator')

    def test_both_android_players_enable_score_reporting(self):
        reports = []
        def play(args):
            reports.append(os.environ.get('UN5_KOTH_RESULT_FILE'))
            return 0

        with patch('mobile.koth.play', side_effect=play):
            for role in ('guest', 'host', 'spectator', 'host'):
                koth.play_round(self.config, dict(self.snapshot, role=role), self.state,
                                self.symbols, self.root / 'round.stop')
                self.assertNotIn('UN5_KOTH_RESULT_FILE', os.environ)
        result = str(self.root / 'result.json')
        self.assertEqual(reports, [result, result, None, result])

    def test_heartbeat_reports_django_roles_and_disconnects(self):
        roles = iter((None, 'guest', 'host', 'spectator'))
        messages = []
        requests = []

        def heartbeat(url, ticket, body):
            requests.append(dict(body))
            if body.get('offline'):
                return {}
            role = next(roles)
            if role == 'spectator':
                self.stop.touch()
            return {**self.snapshot, 'ready': False, 'role': role}

        with (patch('mobile.koth.prepare_files', return_value=(self.state, self.symbols)),
              patch('mobile.koth.wait_for_match') as prepare,
              patch('mobile.koth.release_game'),
              patch('mobile.koth.sync', side_effect=heartbeat),
              patch('mobile.koth.time.sleep')):
            koth.run_koth(self.config, lambda _, message: messages.append(message))

        self.assertEqual([message.splitlines()[0] for message in messages[1:]],
                         [f'KOTH · P5 · {role}' for role in ('En espera', 'P2', 'P1', 'Espectador')])
        prepare.assert_called_once_with(self.config, unittest.mock.ANY)
        self.assertTrue(requests[0]['available'])
        self.assertTrue(requests[-1]['offline'])
