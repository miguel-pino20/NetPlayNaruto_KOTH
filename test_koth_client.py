import json
import io
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

from discord_auth import AccountError
from koth_client import DEFAULT_URL, MembershipStore, enroll, link_account, site_url
from launcher_core import Backend
from urllib.error import HTTPError


class KothClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'memberships.json'
        self.store = MembershipStore(self.path)
        self.url = 'https://events.example.test'
        self.event = {'id': 2, 'version': 4}

    def test_scheduled_registration_uses_official_endpoint_and_verified_session(self):
        from koth_client import TOURNAMENT_FORMATS, scheduled_tournaments, join_tournament, tournament_label
        events = [dict(id=n, name='Copa', format=kind, enrolled=2, max_participants=8, event_date=None)
                  for n, kind in enumerate(TOURNAMENT_FORMATS, 1)]
        with patch('koth_client.api_call', return_value={'events': events}) as api:
            self.assertEqual(scheduled_tournaments(self.url), events)
            api.assert_called_once_with(self.url, 'GET', '/api/netplay/tournaments/', timeout=8)
            api.return_value = {'participant_id': 17}
            for event in events:
                self.assertIn('2/8', tournament_label(event))
                self.assertEqual(join_tournament(self.url, 'session', event['id']), 17)
                api.assert_called_with(self.url, 'POST', f"/api/netplay/tournaments/{event['id']}/join/", {},
                                       timeout=12, extra_headers={'X-Netplay-Session': 'session'}, follow_redirects=False)
            api.reset_mock()
            for url, session in ((self.url, ''), ('http://example.test', 'session')):
                with self.assertRaises(AccountError):
                    join_tournament(url, session, 1)
            api.assert_not_called()

    def test_ready_fixture_is_scoped_to_authenticated_pair_and_event(self):
        from koth_client import assigned_fixture
        fixture = {'event_id': 7, 'fixture_id': 42, 'session': 'round-id', 'role': 'p2',
                   'p1': {'name': 'Alie el'}, 'p2': {'name': 'DRAGON LUCARIO'}}
        with patch('koth_client.api_call', return_value={'fixtures': [dict(fixture, event_id=9), fixture, dict(fixture, fixture_id=43)]}) as api:
            self.assertEqual(assigned_fixture(self.url, 'session', 7), fixture)
            api.assert_called_once_with(self.url, 'GET', '/api/netplay/fixtures/', timeout=8,
                                        extra_headers={'X-Netplay-Session': 'session'}, follow_redirects=False)
            self.assertIsNone(assigned_fixture(self.url, 'session', 8))
            api.return_value = {'fixtures': []}
            self.assertIsNone(assigned_fixture(self.url, 'session', 7))
            with self.assertRaises(AccountError):
                assigned_fixture(self.url, '', 7)

    def test_fixture_client_and_launcher_use_direct_udp_with_automatic_addresses(self):
        from koth_client import wait_fixture
        from launcher_core import zerotier_args
        from netplay import main
        self.path.write_text('fixture files')
        for is_host in (True, False):
            role = 'host' if is_host else 'guest'
            cfg = dict(fixture={'event_id': 7, 'fixture_id': 9}, hill_url=self.url, game='un5',
                       zerotier_address='10.1.2.1')
            command = zerotier_args(cfg, role)
            with patch('netplay.cmd_play') as play:
                main([role, *command])
                args = play.call_args.args[0]
            self.assertEqual(args.server, '')
            self.assertEqual(args.tournament_fixture, [7, 9])
            args.state = args.symbols = self.path
            with patch('koth_client.api_call', return_value={
                    'role': 'p1' if is_host else 'p2', 'ready': True, 'peer_attempt': 'b'*32,
                    'session_epoch': 'e'*32, 'address': '10.1.2.2', 'port': 47400}):
                self.assertTrue(wait_fixture(args, is_host, 'login', lambda: False))
            self.assertEqual(args.session_epoch, 'e'*32)
            if is_host:
                self.assertEqual(args.expect_guest_ip, '10.1.2.2')
            else:
                self.assertEqual(args.connect, '10.1.2.2:47400')

    def test_membership_survives_restart_and_is_scoped_to_site_and_event(self):
        first = self.store.member(self.url, 2)
        self.assertEqual(MembershipStore(self.path).member(self.url, 2), first)
        self.assertNotEqual(self.store.member(self.url, 3)['key'], first['key'])
        self.assertNotEqual(self.store.member('https://other.example.test', 2)['key'], first['key'])

    def test_typo_in_shipped_domain_is_repaired_without_changing_custom_servers(self):
        self.assertEqual(DEFAULT_URL, 'https://narutimateonline.servegame.com')
        self.assertEqual(site_url('https://narultimateonline.sytes.net/'), DEFAULT_URL)
        self.assertEqual(site_url('http://narultimateonline.sytes.net:8077'), 'http://narutimateonline.servegame.com:8077')
        self.assertEqual(site_url('https://narutimateonline.sytes.net/'), DEFAULT_URL)
        self.assertEqual(site_url(DEFAULT_URL + '/'), DEFAULT_URL)
        self.assertEqual(site_url(DEFAULT_URL), DEFAULT_URL)
        self.assertEqual(site_url('https://narutimateonline.sytes.net:8443/custom/'),
                         DEFAULT_URL + ':8443/custom')
        self.assertEqual(site_url(self.url), self.url)
        self.assertEqual(site_url('https://narultimateonline.sytes.net.example.test'),
                         'https://narultimateonline.sytes.net.example.test')

    def test_saved_configuration_url_is_repaired(self):
        import launcher_core
        config = Path(self.directory.name)/'launcher.json'
        for host in ('narultimateonline.sytes.net', 'narutimateonline.sytes.net'):
            with self.subTest(host=host):
                config.write_text(json.dumps({'hill_url': 'https://' + host}))
                with patch.object(launcher_core, 'CONFIG_FILE', config):
                    self.assertEqual(launcher_core.load_config()['hill_url'], DEFAULT_URL)

    def test_membership_key_is_preserved_when_correcting_the_old_default(self):
        credential = {'key': 'a'*32, 'ticket': 'sample-ticket'}
        for host in ('narultimateonline.sytes.net', 'narutimateonline.sytes.net',
                     'narutimateonline.servegame.com'):
            for slash in ('', '/'):
                with self.subTest(host=host, slash=slash):
                    old_key = 'https://' + host + slash + '/events/2'
                    self.path.write_text(json.dumps({old_key: credential}))
                    self.assertEqual(self.store.member(DEFAULT_URL, 2), credential)
                    self.assertEqual(self.store.member(DEFAULT_URL + '/', 2), credential)
                    self.store.save_ticket(DEFAULT_URL, 2, 'updated-ticket')
                    self.assertEqual(self.store.member(DEFAULT_URL, 2)['ticket'], 'updated-ticket')
                    self.assertNotEqual(self.store.member(DEFAULT_URL, 3)['key'], credential['key'])

    @patch('koth_client.api_call')
    def test_lost_enrollment_response_retries_with_same_key(self, api):
        api.side_effect = AccountError('Network error')
        with self.assertRaises(AccountError):
            enroll(self.url, self.event, 'Player', self.store)
        first_key = api.call_args.args[3]['registration_key']
        api.side_effect = None
        api.return_value = {'ticket': 'new-ticket', 'event': self.event}
        enroll(self.url, self.event, 'Player', MembershipStore(self.path))
        self.assertEqual(api.call_args.args[3]['registration_key'], first_key)
        self.assertEqual(self.store.member(self.url, 2)['ticket'], 'new-ticket')

    @patch('koth_client.api_call')
    def test_version_conflict_refreshes_event_once_without_duplicate_identity(self, api):
        api.side_effect = [AccountError('Changed', 409), {'id': 2, 'version': 9},
                           {'ticket': 'new-ticket', 'event': self.event}]
        result = enroll(self.url, self.event, 'Player', self.store, 'existing-code')
        self.assertEqual(result['ticket'], 'new-ticket')
        self.assertEqual(api.call_count, 3)
        self.assertEqual(api.call_args.args[3]['version'], 9)
        self.assertEqual(api.call_args.kwargs['token'], 'existing-code')

    def test_live_board_messages_are_consumed_without_dumping_them_into_console(self):
        backend = Backend.__new__(Backend)
        backend.q = queue.Queue()
        state = {'event': {'id': 2, 'name': 'Arena', 'queue': []}, 'role': 'spectator'}
        process = Mock()
        process.stdout = ['KOTH_STATE '+json.dumps(state)+'\n', 'normal status\n']
        process.wait.return_value = 0
        backend._reader(process)
        events = list(backend.q.queue)
        self.assertEqual(events[0], ('koth_state', state, process))
        self.assertEqual(events[1], ('line', 'normal status'))
        self.assertEqual(events[2], ('exit', 0))

    @patch('discord_auth.urllib.request.urlopen')
    def test_registration_errors_show_django_validation_message(self, request):
        from discord_auth import api_call
        request.side_effect = HTTPError(self.url, 400, 'Bad request', {},
                                        io.BytesIO(b'{"non_field_errors":["Name is already registered."]}'))
        with self.assertRaisesRegex(AccountError, 'Name is already registered'):
            api_call(self.url, 'POST', '/api/netplay/events/2/join/', {})

    @patch('koth_client.api_call')
    def test_verified_session_is_sent_only_in_header_and_link_confirmation_is_required(self, api):
        api.return_value = {'ticket': 'linked-ticket', 'event': self.event, 'account_linked': True}
        enroll(self.url, self.event, 'Player', self.store, netplay_session='private-main-session')
        self.assertEqual(api.call_args.kwargs['extra_headers'], {'X-Netplay-Session': 'private-main-session'})
        self.assertNotIn('private-main-session', str(api.call_args.args[3]))
        api.return_value = {'ticket': 'guest-ticket', 'event': self.event}
        with self.assertRaisesRegex(AccountError, 'Actualiza Django'):
            enroll(self.url, self.event, 'Player', self.store, netplay_session='private-main-session')

    @patch('koth_client.api_call')
    def test_manual_entry_links_personal_code_with_verified_main_account(self, api):
        api.return_value = {'ticket': 'linked-ticket', 'event': self.event, 'account_linked': True}
        result = link_account(self.url, 'guest-code', 'private-main-session')
        self.assertEqual(result['ticket'], 'linked-ticket')
        self.assertEqual(api.call_args.args[2], '/api/netplay/link-account/')
        self.assertEqual(api.call_args.kwargs['token'], 'guest-code')
        self.assertEqual(api.call_args.kwargs['extra_headers'], {'X-Netplay-Session': 'private-main-session'})


if __name__ == '__main__':
    unittest.main()
