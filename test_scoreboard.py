import argparse
import json
import socket
import struct
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import scoreboard as sb


def cfg(**over):
    return sb.merge(sb.DEFAULTS, {'enabled': True, **over})


cfg_ = cfg


class BoardTests(unittest.TestCase):
    def test_count_render_undo_reset(self):
        board = sb.Scoreboard(cfg())
        board.record('p1'); board.record('p2'); board.record('p2'); board.record('draw')
        self.assertEqual(board.render(), 'J1: 1 | J2: 2')
        self.assertEqual(board.snapshot()['draws'], 1)
        board.undo(); board.undo()
        self.assertEqual((board.p1, board.p2, board.draws), (1, 1, 0))
        board.reset()
        self.assertEqual(board.render(), 'J1: 0 | J2: 0')
        self.assertIsNone(board.undo())

    def test_invalid_winner_and_bad_template(self):
        board = sb.Scoreboard(cfg(format='{nope}'))
        with self.assertRaises(ValueError):
            board.record('p3')
        self.assertEqual(board.render(), 'J1: 0 | J2: 0')

    def test_nicks_override_names_only_when_enabled(self):
        board = sb.Scoreboard(cfg())
        board.set_nicks('Ana', '')
        self.assertEqual(board.render(), 'Ana: 0 | J2: 0')
        board.cfg['use_nicks'] = False
        self.assertEqual(board.render(), 'J1: 0 | J2: 0')

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 's.json'
            with patch.object(sb.appdata, 'write_json', lambda p, data, private=False: Path(p).write_text(json.dumps(data))):
                a = sb.Scoreboard(cfg(persist=True), path)
                a.record('p1'); a.record('p1')
                b = sb.Scoreboard(cfg(persist=True), path)
            self.assertEqual(b.p1, 2)

    def test_listener_failure_does_not_break_board(self):
        board = sb.Scoreboard(cfg())
        board.listeners.append(lambda e: 1 / 0)
        board.record('p1')
        self.assertEqual(board.p1, 1)


class DetectorTests(unittest.TestCase):
    def make(self, values, **extra):
        clock = [0.0]
        seq = iter(values)
        got = []
        det = sb.ResultDetector({'result_addr': '0x100', 'p1_value': 1, 'p2_value': [2, 3], 'draw_value': 9,
                                 'poll_ms': 20, 'min_gap_s': 1, **extra},
                                lambda a, s: next(seq), got.append, lambda: clock[0])
        def run():
            for _ in values:
                det.tick()
                clock[0] += 0.05
        return det, got, run

    def test_fires_once_per_transition(self):
        det, got, run = self.make([0, 1, 1, 1, 0, 2, 2])      # 2 chega 0.05 s depois do 1: abaixo de min_gap_s
        run()
        self.assertEqual(got, ['p1'])      # 2 arrives only 0.05 s after p1: below min_gap_s
        det2, got2, run2 = self.make([0, 1, 1, 0, 3, 3], min_gap_s=0)
        run2()
        self.assertEqual(got2, ['p1', 'p2'])

    def test_value_list_mask_and_draw(self):
        det, got, run = self.make([0x30, 0x39], mask=0x0F, min_gap_s=0)
        run()
        self.assertEqual(got, ['draw'])

    def test_inactive_without_address_and_survives_read_errors(self):
        self.assertFalse(sb.ResultDetector({}, lambda a, s: 0, print).active)
        def boom(a, s): raise OSError
        det = sb.ResultDetector({'result_addr': '1', 'p1_value': 1}, boom, print)
        self.assertIsNone(det.tick())

    def test_stale_result_at_start_does_not_count(self):
        det, got, run = self.make([1, 1, 1, 0, 2], min_gap_s=0)
        run()
        self.assertEqual(got, ['p2'])

    def test_accel2_default_profile(self):
        self.assertEqual(sb.profile_config(cfg(), 'SLPS-25837', '12345678')['detector']['result_addr'], '')  # outro mod
        d = sb.profile_config(cfg(), 'SLPS-25837', 'C0659AD1')['detector']
        self.assertEqual((d['result_addr'], d['p1_value'], d['p2_value']), ('0x607670', 1, 2))
        self.assertTrue(sb.ResultDetector(d, lambda a, s: 0, print).active)

    def test_bad_size(self):
        with self.assertRaises(ValueError):
            sb.ResultDetector({'size': 3}, None, None)


class ProfileTests(unittest.TestCase):
    def test_profile_by_serial_and_pointer_read(self):
        c = cfg(profiles={'SLPS-25837': {'detector': {'result_addr': '0x607620', 'deref': True, 'offset': 0,
                                                     'size': 4, 'p1_value': 0x14, 'poll_ms': 20, 'min_gap_s': 0}}})
        self.assertEqual(sb.profile_config(c, 'SLPS_258.37')['detector']['p1_value'], 0x14)
        self.assertEqual(sb.profile_config(c, 'SLUS-55606')['detector']['p1_value'], None)
        mem = {0x607620: 0xC427F0, 0xC427F0: 0}
        with tempfile.TemporaryDirectory() as d:
            c['outputs'] = {'file': {'dir': d}}
            svc = sb.build(c, read=lambda a, s: mem.get(a, 0), state_path=Path(d) / 's.json',
                           log=lambda m: None, serial='SLPS-25837')
            self.assertTrue(svc.detector.active)
            self.assertIsNone(svc.detector.tick())            # arma ao ver o valor neutro
            mem[0xC427F0] = 0x14
            svc.detector.next_poll = 0
            self.assertEqual(svc.detector.tick(), 'p1')
            svc.close()

    def test_crc_profile_beats_serial_and_separates_mods(self):
        c = cfg(profiles={'SLUS-55606': {'detector': {'result_addr': '0x1', 'p1_value': 1}},
                          'SLUS-55606:688C83D6': {'detector': {'result_addr': '0x2', 'p1_value': 1}}})
        self.assertEqual(sb.profile_config(c, 'SLUS-55606', '688c83d6')['detector']['result_addr'], '0x2')
        self.assertEqual(sb.profile_config(c, 'SLUS-55606', 'AAAAAAAA')['detector']['result_addr'], '0x1')
        only_crc = cfg(profiles={'SLUS-55606:688C83D6': {'detector': {'result_addr': '0x2'}}})
        self.assertEqual(sb.profile_config(only_crc, 'SLUS-55606', 'AAAAAAAA')['detector']['result_addr'], '')
        self.assertEqual(sb.profile_config(only_crc, 'SLUS-55606', '')['detector']['result_addr'], '')

    def test_null_pointer_is_ignored(self):
        det = sb.ResultDetector({'result_addr': '0x10', 'deref': True, 'p1_value': 0}, lambda a, s: 0, print)
        self.assertIsNone(det.tick())


class FakeUn6:
    """RAM minima do UN6: status em [[0x617D20]], lutadores em [[[[0x617D04]+0x18]+8]+4/+8], vida float +0x6C."""
    def __init__(self):
        self.m = { 0x617D04: 0x300000, 0x300018: 0x310000, 0x310008: 0x320000,
                  0x320004: 0x400000, 0x320008: 0x500000, 0x400068: 80, 0x500068: 117,
                  0x617D20: 0x200000}
        self.set(15, 1.0, 1.0)

    def set(self, status, hp1=None, hp2=None):
        self.m[0x200000] = status
        f = lambda v: struct.unpack('<I', struct.pack('<f', v))[0]
        if hp1 is not None:
            self.m[0x40006C], self.m[0x50006C] = f(hp1), f(hp2)

    def read(self, a, s):
        return self.m.get(a, 0)


class HpDetectorTests(unittest.TestCase):
    def run_seq(self, seq):
        ram, got = FakeUn6(), []
        cfg = sb.profile_config(cfg_(), 'SLUS-55606', '688C83D6')['detector']
        det = sb.make_detector(cfg, ram.read, lambda who, chars=None: got.append(who))
        self.assertIsInstance(det, sb.HpDetector)
        t = 0.0
        for step in seq:
            ram.set(*step)
            det.tick(now=t)
            t += 1
        return got

    # Caminhos reais do UN6, copiados do log do `watch` de 2026-11-20.
    def test_ko_each_side(self):
        self.assertEqual(self.run_seq([(15, 1, 1), (15, 1.0, 0.0), (16,), (17,), (19,), (20,), (21,), (7,)]), ['p1'])
        self.assertEqual(self.run_seq([(15, 1, 1), (15, 0.0, 1.0), (17,), (19,), (20,)]), ['p2'])

    def test_time_win_uses_more_hp(self):
        self.assertEqual(self.run_seq([(15, 1, 1), (15, 1.0, 0.884), (17,), (19,), (20,), (21,), (7,)]), ['p1'])

    def test_double_ko_reaching_result_screen_is_draw(self):
        self.assertEqual(self.run_seq([(15, 1, 1), (15, 0.0, 0.0), (16,), (17,), (19,), (20,)]), ['draw'])

    def test_quit_by_menu_and_time_draw_do_not_count(self):
        # mesmo caminho para os dois: 0xF -> 0x10 -> 0x11 -> 0x3 -> 0x5 -> 0x6 -> 0x7
        path = [(16,), (17,), (3,), (5,), (6,), (7,)]
        self.assertEqual(self.run_seq([(15, 1.0, 1.0)] + path), [])
        self.assertEqual(self.run_seq([(15, 0.6, 0.3)] + path), [])
        self.assertEqual(self.run_seq([(15, 1, 1), (9,), (7,)]), [])        # direto para a selecao
        self.assertEqual(self.run_seq([(15, 1, 1), (0,), (20,)]), [])       # carregou um save na tela de resultado

    def test_one_result_per_fight_and_new_fight_counts_again(self):
        seq = [(15, 1, 1), (15, 1, 0), (16,), (19,), (20,), (20,), (21,), (7,),
               (15, 1, 1), (15, 0, 1), (17,), (19,), (20,)]
        self.assertEqual(self.run_seq(seq), ['p1', 'p2'])

    def test_bad_pointers_are_ignored(self):
        ram, got = FakeUn6(), []
        det = sb.make_detector(sb.profile_config(cfg_(), 'SLUS-55606', '688C83D6')['detector'], ram.read,
                               lambda who, chars=None: got.append(who))
        ram.m[0x617D04] = 0
        det.tick(now=0); ram.set(16); det.tick(now=1); ram.set(20); det.tick(now=2)
        self.assertEqual(got, [])

    def test_characters_come_with_the_result(self):
        ram = FakeUn6()
        with tempfile.TemporaryDirectory() as d:
            c = cfg_(outputs={'file': {'dir': d}}, format='{name1} ({char1}) {p1} x {p2} ({char2}) {name2}')
            svc = sb.build(c, read=ram.read, state_path=Path(d) / 's.json', log=lambda m: None,
                           serial='SLUS-55606', crc='688C83D6')
            det = svc.detector
            det.tick(now=0); ram.set(15, 1.0, 0.0); det.tick(now=1); ram.set(16); det.tick(now=2)
            ram.set(20); det.tick(now=3)
            last = svc.board.snapshot()['last']
            svc.close()
        self.assertEqual(last['winner'], 'p1')
        self.assertEqual(last['chars']['p1'], {'id': 80, 'code': 'hnw', 'name': 'Hinata Hyuga'})
        self.assertEqual(last['chars']['p2'], {'id': 117, 'code': 'obt', 'name': 'Obito'})   # personagem do mod
        self.assertEqual(svc.board.render(), 'J1 (Hinata Hyuga) 1 x 0 (Obito) J2')

    def test_character_table_covers_base_and_mod(self):
        table = sb.load_characters('chars_un6.json')
        self.assertEqual(table['58']['name'], 'Sakura Haruno')
        self.assertEqual([table[k]['code'] for k in ('117', '119', '120')], ['obt', 'swv', 'nwx'])
        self.assertEqual([table[k]['name'] for k in ('100', '105', '121')], ['Kakashi Anbu', 'Suigetsu', 'Iruka'])
        self.assertTrue(all(v['name'] for v in table.values()))

    def test_matheus_build_does_not_get_this_profile(self):
        self.assertNotEqual(sb.profile_config(cfg_(), 'SLUS-55606', 'DEADBEEF')['detector'].get('mode'), 'hp')


class SinkTests(unittest.TestCase):
    def test_file_sink_writes_text_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            board = sb.Scoreboard(cfg())
            sink = sb.FileSink({'dir': d, 'text': 'p.txt', 'json': 'p.json'}, board)
            self.assertEqual((Path(d) / 'p.txt').read_text().strip(), 'J1: 0 | J2: 0')
            board.record('p2')
            sink.send(None)
            self.assertEqual(json.loads((Path(d) / 'p.json').read_text())['p2'], 1)

    def test_webhook_discord_payload(self):
        board = sb.Scoreboard(cfg())
        sink = sb.WebhookSink({'url': 'https://example.test/hook', 'style': 'discord', 'message': 'Placar {format}'}, board)
        event = board.record('p1')
        with patch('scoreboard._post') as post:
            sink.send(event)
        self.assertEqual(post.call_args.args[1], {'content': 'Placar J1: 1 | J2: 0'})
        with self.assertRaises(ValueError):
            sb.WebhookSink({'url': 'ftp://x'}, board)

    def test_django_payload_matches_server_contract(self):
        board = sb.Scoreboard(cfg())
        with patch.dict('os.environ', {'UN5_NETPLAY_SESSION': ''}):
            with self.assertRaises(ValueError):
                sb.DjangoSink(sb.DEFAULTS['outputs']['django'] | {'url': 'https://site.test'}, board)
        with patch.dict('os.environ', {'UN5_NETPLAY_SESSION': 'discord-session'}):
            sink = sb.DjangoSink(sb.DEFAULTS['outputs']['django'] | {'url': 'https://site.test/'}, board,
                                 '2c46ea8d15f9478c9c5a6e829231a730')
        board.set_nicks('LUCARIO DRAGO', 'Indiana')
        board.record('p1', 'memoria')
        event = board.record('p2', 'memoria', {'p1': {'id': 106, 'code': 'kar', 'name': 'Karin'},
                                               'p2': {'id': 92, 'code': 'sai', 'name': 'Sai'}})
        with patch('scoreboard._post') as post:
            sink.send(event)
        url, body, headers = post.call_args.args
        self.assertEqual(url, 'https://site.test/api/netplay/casual/result/')
        self.assertEqual(headers, {'X-Netplay-Session': 'discord-session',
                                   'Idempotency-Key': '2c46ea8d15f9478c9c5a6e829231a730-2'})
        # mesmos campos e valores do exemplo enviado pelo servidor (exceto timestamp)
        expected = {'event': 'result', 'winner': 'p2', 'source': 'memoria',
                    'score': {'p1': 1, 'p2': 1, 'draws': 0},
                    'names': {'p1': 'LUCARIO DRAGO', 'p2': 'Indiana'},
                    'characters': {'p1': {'id': 106, 'code': 'kar', 'name': 'Karin'},
                                   'p2': {'id': 92, 'code': 'sai', 'name': 'Sai'}},
                    'match_number': 2, 'session': '2c46ea8d15f9478c9c5a6e829231a730',
                    'idempotency_key': '2c46ea8d15f9478c9c5a6e829231a730-2'}
        self.assertEqual({k: v for k, v in body.items() if k != 'timestamp'}, expected)
        self.assertEqual(sorted(body), sorted(list(expected) + ['timestamp']))

    def test_session_id_koth_casual_and_none(self):
        A = argparse.Namespace
        self.assertEqual(sb.session_id(A(session_epoch='2c46ea8d', room='')), '2c46ea8d')   # KOTH
        self.assertEqual(sb.session_id(A(session_epoch='0', room='')), '')                 # sem nada
        self.assertEqual(sb.session_id(A(session_epoch='0', room='sala9')), 'sala9')       # casual (guest)
        self.assertEqual(sb.session_id(A(session_epoch='0'), room='sala7'), 'sala7')       # casual (host)

    def test_django_key_is_the_same_on_both_pcs(self):
        keys = []
        for _ in range(2):
            board = sb.Scoreboard(cfg())
            sink = sb.DjangoSink({'url': 'https://site.test', 'token': 't'}, board, 'sess')
            board.record('p1'); time.sleep(0.01)
            with patch('scoreboard._post') as post:
                sink.send(board.record('p2'))
            keys.append(post.call_args.args[2]['Idempotency-Key'])
        self.assertEqual(keys, ['sess-2', 'sess-2'])

    def test_dispatcher_isolates_failures(self):
        calls = []
        class Bad:
            label = 'bad'
            def send(self, e): raise RuntimeError('url-secret')
        class Good:
            label = 'good'
            def send(self, e): calls.append(e)
        logs = []
        disp = sb.Dispatcher([Bad(), Good()], logs.append)
        disp.push({'event': 'result'})
        disp.close()
        self.assertEqual(len(calls), 1)
        self.assertNotIn('url-secret', ' '.join(logs))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.board = sb.Scoreboard(cfg())
        self.sink = sb.HttpSink({'host': '127.0.0.1', 'port': 0, 'token': 'tok'}, self.board)
        self.base = f'http://127.0.0.1:{self.sink.port}'
        self.addCleanup(self.sink.close)

    def call(self, path, method='GET', headers=None):
        req = urllib.request.Request(self.base + path, method=method, headers=headers or {}, data=b'' if method == 'POST' else None)
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, ''

    def test_get_and_authorized_post(self):
        self.assertEqual(json.loads(self.call('/score')[1])['text'], 'J1: 0 | J2: 0')
        self.assertEqual(self.call('/score/p1', 'POST')[0], 403)
        self.assertEqual(self.call('/score/p1', 'POST', {'Authorization': 'Bearer tok', 'Origin': 'http://evil'})[0], 403)
        self.assertEqual(self.call('/score/p1', 'POST', {'Authorization': 'Bearer tok'})[0], 200)
        self.assertEqual(self.call('/text')[1], 'J1: 1 | J2: 0')
        self.assertEqual(self.call('/score/undo', 'POST', {'Authorization': 'Bearer tok'})[0], 200)
        self.assertEqual(self.board.p1, 0)

    def test_no_token_disables_writes(self):
        sink = sb.HttpSink({'host': '127.0.0.1', 'port': 0}, self.board)
        self.addCleanup(sink.close)
        req = urllib.request.Request(f'http://127.0.0.1:{sink.port}/score/p1', method='POST', data=b'')
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(e.exception.code, 403)

    def test_websocket_hello_and_push(self):
        s = socket.create_connection(('127.0.0.1', self.sink.port), timeout=3)
        s.sendall(b'GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                  b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n')
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += s.recv(4096)
        head, _, rest = buf.partition(b'\r\n\r\n')
        self.assertIn(b'101', head)
        self.assertIn(b's3pPLMBiTxaQ9kYGzzhZRbK+xOo=', head)      # RFC 6455 example accept key
        def frame(rest):
            while len(rest) < 4:
                rest += s.recv(4096)
            hdr, n = (2, rest[1]) if rest[1] < 126 else (4, struct.unpack('>H', rest[2:4])[0])
            while len(rest) < hdr + n:
                rest += s.recv(4096)
            return json.loads(rest[hdr:hdr + n]), rest
        hello, _ = frame(rest)
        self.assertEqual(hello['event'], 'hello')
        time.sleep(0.1)
        self.sink.send(self.board.record('p1'))
        data = s.recv(4096)
        self.assertEqual(data[0], 0x81)
        self.assertIn(b'"event": "result"', data)
        s.close()


class BuildTests(unittest.TestCase):
    def test_disabled_returns_none_and_guest_skips_external(self):
        self.assertIsNone(sb.build(sb.merge(sb.DEFAULTS, {})))
        with tempfile.TemporaryDirectory() as d:
            c = cfg(outputs={'file': {'dir': d}, 'webhook': {'enabled': True, 'url': 'https://example.test/h'}})
            svc = sb.build(c, is_host=False, state_path=Path(d) / 's.json', log=lambda m: None)
            self.assertEqual([x.label for x in svc.sinks], ['arquivo'])
            svc.close()

    def test_detector_feeds_outputs_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            c = cfg(outputs={'file': {'dir': d}}, detector={'result_addr': '0x10', 'p2_value': 5, 'poll_ms': 20})
            value = [0]
            svc = sb.build(c, read=lambda a, s: value[0], state_path=Path(d) / 's.json', log=lambda m: None)
            svc.tick()
            value[0] = 5
            svc.detector.next_poll = 0                   # sem depender do relogio (resolucao de ~15 ms no Windows)
            svc.tick()
            time.sleep(0.2)
            svc.close()
            self.assertEqual((Path(d) / 'placar.txt').read_text().strip(), 'J1: 0 | J2: 1')


if __name__ == '__main__':
    unittest.main()
