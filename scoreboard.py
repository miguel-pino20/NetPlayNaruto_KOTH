#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Placar de vitorias (J1: 2 | J2: 5) com saidas configuraveis.

Fluxo:  detector (le a memoria do jogo via PINE)  ->  Scoreboard (estado)  ->  saidas
        (arquivo txt/json para o OBS, API HTTP local + WebSocket, webhook/Discord, Django).

Tudo e opcional e fica DESLIGADO ate `enabled: true` em scoreboard.json (pasta de dados do app).
Uma falha em qualquer saida nunca interrompe a partida: as saidas rodam em uma thread propria.

ATENCAO: o endereco de memoria que indica "quem venceu" ainda NAO esta validado (ver
docs/REGLAS-Y-PRUEBAS-KOTH.md). Use `python scoreboard.py probe` / `diff` para descobri-lo e preencha
`detector` na configuracao. Enquanto isso o placar tambem pode ser alterado a mao pela API local ou
por `python scoreboard.py test`.

Comandos:  init | show | test p1|p2|draw | probe | diff
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import queue
import struct
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import appdata

CONFIG_NAME = 'scoreboard.json'
STATE_NAME = 'scoreboard_state.json'
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
WINNERS = ('p1', 'p2', 'draw')

DEFAULTS = {
    'enabled': False,
    # Nomes mostrados. Com use_nicks, o apelido de cada jogador na partida tem prioridade.
    'names': {'p1': 'J1', 'p2': 'J2'},
    'use_nicks': True,
    # Campos: {name1} {name2} {p1} {p2} {draws} {total} {leader} {char1} {char2} (personagens da ultima luta)
    'format': '{name1}: {p1} | {name2}: {p2}',
    'persist': False,                # guarda o placar entre execucoes (scoreboard_state.json)
    'external_only_host': True,      # webhook/Django so no host, para nao duplicar o envio
    # Partidas casuais pela rede do Netplay (salas online, sem ZeroTier): liga o placar e o envio ao site sozinho,
    # com a sessao de Discord do launcher. false = so com enabled/outputs.django configurados a mao.
    'auto_online': True,
    'site_url': 'https://narutimateonline.servegame.com',
    'outputs': {
        'file': {'enabled': True, 'dir': '', 'text': 'placar.txt', 'json': 'placar.json'},
        'http': {'enabled': False, 'host': '127.0.0.1', 'port': 47500,
                 'token': ''},       # com token, POST /score/{p1|p2|draw|undo|reset} fica habilitado
        'webhook': {'enabled': False, 'url': '', 'style': 'discord',     # discord | json
                    'message': '{format}', 'headers': {}},
        # Contrato do servidor (2026-11-20): POST /api/netplay/casual/result/ com a sessao de Discord do Netplay no
        # cabecalho X-Netplay-Session (o launcher ja passa UN5_NETPLAY_SESSION ao processo da luta) e
        # Idempotency-Key = "<session>-<match_number>", igual nos dois PCs.
        'django': {'enabled': False, 'url': '', 'path': '/api/netplay/casual/result/',
                   'auth_header': 'X-Netplay-Session', 'auth_scheme': '',
                   'token': '', 'token_env': ['UN5_NETPLAY_SESSION', 'UN5_SCOREBOARD_SESSION']},
    },
    # Onde o jogo guarda o resultado. Sem endereco o detector fica desligado.
    'detector': {'result_addr': '', 'size': 1, 'mask': 255,
                 'p1_value': None, 'p2_value': None, 'draw_value': None,   # int ou lista de ints
                 'deref': False, 'offset': 0,   # deref: result_addr guarda um PONTEIRO; le-se em [result_addr]+offset
                 'poll_ms': 100, 'min_gap_s': 5.0},
    # Um detector por jogo, escolhido pelo serial do disco (PINE). Sobrepoe `detector`.
    # Ex.: {"SLPS-25837": {"detector": {"result_addr": "0x607620", "deref": true, ...}}}
    # SLPS-25837 (Accel 2 JP): word em 0x607670 = 0 na luta e 1 / 2 quando P1 / P2 vence (saves de 2026-11-20).
    # Validado com 1 vitoria de P1, 2 de P2 e 1 derrota contra a COM; empate ainda nao capturado.
    # SLUS-55606:688C83D6 (UN6 desta build): status da batalha em [[0x617D20]] (0xF luta, 0x10..0x14 fim/resultado);
    # lutador i em [[[[0x617D04]+0x18]+8]+4+4i] (o mesmo caminho do GetPlayerData do NetPad); vida = float em +0x6C
    # (1.0 cheia, 0 = KO). Validado em 2026-11-20: KO de P1 e de P2, vitoria por tempo (com personagem do mod),
    # saida pelo menu (nao conta). Empate por tempo faz o mesmo caminho da saida pelo menu: nao conta.
    # So para este CRC: o mod do Matheus usa o mesmo serial com outro layout.
    # So para o CRC testado: Evolution e outros mods do Accel 2 usam o mesmo serial com outro executavel.
    'profiles': {'SLPS-25837:C0659AD1': {'detector': {'result_addr': '0x607670', 'size': 4, 'p1_value': 1,
                                                      'p2_value': 2}},
                 'SLUS-55606:688C83D6': {'detector': {'mode': 'hp', 'status_addr': '0x617D20', 'status_deref': True,
                                                      'fight_value': 15, 'pass_values': [16, 17],
                                                      'result_values': [19, 20],
                                                      'players_chain': ['0x617D04', '0x18', '0x8'],
                                                      'player_offsets': [4, 8], 'hp_offset': '0x6C',
                                                      'char_offset': '0x68', 'characters_file': 'chars_un6.json'}}},
}


def merge(base, extra):
    """Mescla `extra` sobre uma copia de `base` (dicts em profundidade)."""
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def config_path():
    return Path(os.environ.get('UN5_SCOREBOARD_CONFIG') or appdata.DATA_DIR / CONFIG_NAME)


def load_config(path=None):
    path = Path(path) if path else config_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return merge(DEFAULTS, data if isinstance(data, dict) else {})
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


# ---------------------------------------------------------------------------------------------------------------
class Scoreboard:
    """Estado do placar. Thread-safe; cada mudanca gera um evento para os ouvintes."""

    def __init__(self, config, state_path=None):
        self.cfg = config
        self.lock = threading.RLock()
        self.p1 = self.p2 = self.draws = 0
        self.history = []                                   # [{'winner','ts','source','n'}]
        self.nicks = {'p1': '', 'p2': ''}
        self.players = {}
        self.listeners = []
        self.state_path = Path(state_path) if state_path else None
        if self.state_path and config.get('persist'):
            self._load()

    # -- nomes e texto ------------------------------------------------------------------------------------------
    def set_nicks(self, p1='', p2=''):
        with self.lock:
            self.nicks = {'p1': p1 or '', 'p2': p2 or ''}

    def name(self, who):
        with self.lock:
            if self.players.get(who, {}).get('name'):
                return self.players[who]['name']
            if self.cfg.get('use_nicks') and self.nicks.get(who):
                return self.nicks[who]
            return str(self.cfg['names'].get(who) or who.upper())

    def render(self, template=None):
        with self.lock:
            lead = 'p1' if self.p1 > self.p2 else 'p2' if self.p2 > self.p1 else ''
            chars = (self.history[-1].get('chars') or {}) if self.history else {}
            fields = dict(name1=self.name('p1'), name2=self.name('p2'), p1=self.p1, p2=self.p2, draws=self.draws,
                          total=self.p1 + self.p2 + self.draws, leader=self.name(lead) if lead else '',
                          char1=(chars.get('p1') or {}).get('name', ''), char2=(chars.get('p2') or {}).get('name', ''))
            try:
                return (template or self.cfg['format']).format(**fields)
            except (KeyError, IndexError, ValueError):
                return DEFAULTS['format'].format(**fields)

    def snapshot(self):
        with self.lock:
            return {'p1': self.p1, 'p2': self.p2, 'draws': self.draws,
                    'total': self.p1 + self.p2 + self.draws, 'players': self.players,
                    'names': {'p1': self.name('p1'), 'p2': self.name('p2')},
                    'text': self.render(), 'updated': time.time(),
                    'last': self.history[-1] if self.history else None}

    # -- mudancas -----------------------------------------------------------------------------------------------
    def record(self, winner, source='manual', chars=None, fight_number=None):
        if winner not in WINNERS:
            raise ValueError(f'winner deve ser um de {WINNERS}')
        with self.lock:
            attr = {'p1': 'p1', 'p2': 'p2', 'draw': 'draws'}[winner]
            setattr(self, attr, getattr(self, attr) + 1)
            entry = {'winner': winner, 'ts': time.time(), 'source': source,
                     'n': self.p1 + self.p2 + self.draws}
            if self.players:
                entry['players'] = self.players
            if fight_number is not None:
                entry['fight_number'] = fight_number
            if chars:
                entry['chars'] = chars                      # {'p1': {'id', 'code', 'name'}, 'p2': {...}}
            self.history.append(entry)
            return self._changed('result', entry)

    def undo(self):
        with self.lock:
            if not self.history:
                return None
            entry = self.history.pop()
            attr = {'p1': 'p1', 'p2': 'p2', 'draw': 'draws'}[entry['winner']]
            setattr(self, attr, max(0, getattr(self, attr) - 1))
            return self._changed('undo', entry)

    def reset(self):
        with self.lock:
            self.p1 = self.p2 = self.draws = 0
            self.history.clear()
            return self._changed('reset', None)

    def _changed(self, kind, entry):
        event = {'event': kind, 'entry': entry, **self.snapshot()}
        self._save()
        for listener in list(self.listeners):
            try:
                listener(event)
            except Exception:                               # noqa: BLE001 - uma saida nunca derruba o placar
                pass
        return event

    # -- persistencia -------------------------------------------------------------------------------------------
    def _save(self):
        if not (self.state_path and self.cfg.get('persist')):
            return
        try:
            appdata.write_json(self.state_path, {'p1': self.p1, 'p2': self.p2, 'draws': self.draws,
                                                 'history': self.history[-200:]})
        except OSError:
            pass

    def _load(self):
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
            self.p1, self.p2, self.draws = (max(0, int(data.get(k, 0))) for k in ('p1', 'p2', 'draws'))
            self.history = [h for h in data.get('history', []) if isinstance(h, dict)]
        except (OSError, ValueError, TypeError):
            pass


# ---------------------------------------------------------------------------------------------------------------
class ResultDetector:
    """Le um valor da memoria do jogo e avisa UMA vez quando ele passa a indicar vitoria de P1/P2 ou empate.

    Rearma quando o valor volta a nao ser um resultado, e ignora repeticoes em menos de `min_gap_s`.
    `read` e uma funcao (addr, size) -> int; assim da para testar sem PCSX2."""

    def __init__(self, cfg, read, on_result, clock=time.monotonic):
        self.read, self.on_result, self.clock = read, on_result, clock
        self.addr = str(cfg.get('result_addr') or '').strip()
        self.addr = int(self.addr, 0) if self.addr else None
        self.deref, self.offset = bool(cfg.get('deref')), int(str(cfg.get('offset', 0)), 0)
        self.size = int(cfg.get('size', 1))
        if self.size not in (1, 2, 4):
            raise ValueError('detector.size deve ser 1, 2 ou 4')
        self.mask = int(cfg.get('mask', 0xFF))
        self.map = {}
        for who, key in (('p1', 'p1_value'), ('p2', 'p2_value'), ('draw', 'draw_value')):
            values = cfg.get(key)
            for v in ([] if values is None else values if isinstance(values, list) else [values]):
                self.map[int(v)] = who
        self.interval = max(0.02, int(cfg.get('poll_ms', 100)) / 1000)
        self.min_gap = float(cfg.get('min_gap_s', 5.0))
        # Desarmado ate ver um valor "sem resultado": o jogo deixa o resultado da luta anterior na RAM
        # (na selecao de personagem o valor ainda e 1), e isso nao pode contar como vitoria nova.
        self.fight_number = 0
        self.armed, self.next_poll, self.last_fire = False, 0.0, -1e9

    @property
    def active(self):
        return self.addr is not None and bool(self.map)

    def tick(self):
        if not self.active:
            return None
        now = self.clock()
        if now < self.next_poll:
            return None
        self.next_poll = now + self.interval
        try:
            addr = self.addr
            if self.deref:
                base = self.read(addr, 4)
                if not 0x100000 <= base < 0x2000000 or base & 3:   # ponteiro invalido: nao ha objeto agora
                    if not self.armed:
                        self.fight_number += 1
                    self.armed = True
                    return None
                addr = base + self.offset
            value = self.read(addr, self.size) & self.mask
        except Exception:                                   # noqa: BLE001 - uma leitura falha nunca para a partida
            return None
        who = self.map.get(value)
        if who is None:
            if not self.armed:
                self.fight_number += 1
            self.armed = True
            return None
        if not self.armed or now - self.last_fire < self.min_gap:
            return None
        self.armed, self.last_fire = False, now
        self.on_result(who)
        return who


def _int(value):
    return int(str(value), 0)


class HpDetector:
    """Decide o vencedor pela VIDA dos lutadores, confirmado pela tela de resultado do jogo.

    Enquanto o status da batalha vale `fight_value`, guarda a vida (float, 1.0 = cheia) e o personagem de P1 e P2.
    Ao sair da luta, a ultima leitura fica pendente: so vira resultado se o jogo passar pelos `pass_values` e chegar a
    um dos `result_values` (tela de resultado). Os objetos dos lutadores ja nao existem nessa tela, por isso a decisao
    usa a leitura feita ainda na luta. Qualquer outro caminho descarta a leitura.

    Observado no UN6 (2026-11-20): KO e vitoria por tempo -> 0x11/0x13 -> 0x14 (resultado); empate por tempo e sair
    pelo menu -> 0x10 -> 0x11 -> 0x3 (volta a selecao) com o MESMO caminho e a mesma vida, entao nao contam: o jogo
    nao distingue os dois e empate nao da ponto."""

    def __init__(self, cfg, read, on_result):
        self.read, self.on_result = read, on_result
        self.status_addr = _int(cfg['status_addr'])
        self.status_deref = bool(cfg.get('status_deref', True))
        self.fight = _int(cfg.get('fight_value', 0xF))
        self.passing = {_int(v) for v in cfg.get('pass_values', [0x10, 0x11])}
        self.results = {_int(v) for v in cfg.get('result_values', [0x13, 0x14])}
        self.chain = [_int(v) for v in cfg['players_chain']]
        self.slots = [_int(v) for v in cfg.get('player_offsets', [4, 8])]
        self.hp_off = _int(cfg.get('hp_offset', 0x6C))
        self.eps = float(cfg.get('ko_epsilon', 0.0005))
        self.interval = max(0.02, int(cfg.get('poll_ms', 100)) / 1000)
        self.char_off = _int(cfg['char_offset']) if cfg.get('char_offset') not in (None, '') else None
        self.on_status = None                               # depuracao: chamado a cada mudanca de status
        self.char_table = load_characters(cfg.get('characters_file'))
        self.next_poll, self.last_status, self.hp, self.chars = 0.0, None, None, None
        self.fight_number = 0
        self.pending = None                                 # (vida, personagens) da luta que acabou de sair

    active = True

    def character(self, cid):
        info = self.char_table.get(str(cid)) or {}
        return {'id': cid, 'code': info.get('code', ''),
                'name': info.get('name') or (info.get('code') or f'#{cid}').upper()}

    @staticmethod
    def _ptr(v):
        return 0x100000 <= v < 0x2000000 and not v & 3

    def _status(self):
        v = self.read(self.status_addr, 4)
        if self.status_deref:
            if not self._ptr(v):
                return None
            v = self.read(v, 4)
        return v & 0xFF

    def _hp(self):
        a = self.chain[0]
        for step in self.chain[1:]:
            a = self.read(a, 4)
            if not self._ptr(a):
                return None
            a += step
        a = self.read(a, 4)
        if not self._ptr(a):
            return None
        out, ids = [], []
        for slot in self.slots:
            obj = self.read(a + slot, 4)
            if not self._ptr(obj):
                return None
            hp = struct.unpack('<f', struct.pack('<I', self.read(obj + self.hp_off, 4) & 0xFFFFFFFF))[0]
            if not 0.0 <= hp <= 1.5:                        # nao e vida (objeto em troca): ignora a leitura
                return None
            out.append(hp)
            if self.char_off is not None:
                ids.append(self.read(obj + self.char_off, 4))
        if ids:
            self.chars = {'p1': self.character(ids[0]), 'p2': self.character(ids[1])}
        return tuple(out)

    def decide(self, hp):
        h1, h2 = hp
        ko1, ko2 = h1 <= self.eps, h2 <= self.eps
        if ko1 and ko2:
            return 'draw'
        if ko2:
            return 'p1'
        if ko1:
            return 'p2'
        if abs(h1 - h2) <= self.eps:
            return 'draw'
        return 'p1' if h1 > h2 else 'p2'

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if now < self.next_poll:
            return None
        self.next_poll = now + self.interval
        who = chars = None
        try:
            status = self._status()
            if status is None:
                return None
            if status == self.fight and self.last_status != self.fight:
                self.fight_number += 1
            if status != self.last_status and self.on_status:
                self.on_status(self.last_status, status, self.hp or (self.pending or (None,))[0])
            if status == self.fight:
                self.pending = None
                hp = self._hp()
                if hp is not None:
                    self.hp = hp
            elif self.last_status == self.fight:            # acabou de sair da luta: guarda a ultima leitura
                self.pending = (self.hp, self.chars) if self.hp is not None else None
                self.hp = self.chars = None
            if self.pending is not None and status != self.fight:
                if status in self.results:
                    (hp, chars), self.pending = self.pending, None
                    who = self.decide(hp)
                elif status not in self.passing:            # voltou a selecao, menu, carregou save...
                    self.pending = None
            self.last_status = status
        except Exception:                                   # noqa: BLE001 - leitura falha nunca para a partida
            return None
        if who:
            self.on_result(who, chars)
        return who


def load_characters(path):
    """{ 'ID': {'code', 'name'} } de um JSON (caminho relativo a este arquivo). Arquivo ausente: tabela vazia."""
    if not path:
        return {}
    path = Path(path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        table = data.get('characters', data)
        return table if isinstance(table, dict) else {}
    except (OSError, ValueError):
        return {}


def make_detector(cfg, read, on_result):
    if (cfg or {}).get('mode') == 'hp':
        return HpDetector(cfg, read, on_result)
    return ResultDetector(cfg or {}, read, on_result)


# ---------------------------------------------------------------------------------------------------------------
class Dispatcher:
    """Fila + thread unica: envia cada evento para as saidas sem bloquear o loop da partida."""

    def __init__(self, sinks, log=print):
        self.sinks, self.log = sinks, log
        self.q = queue.Queue(maxsize=200)
        self.thread = threading.Thread(target=self._run, daemon=True, name='scoreboard-out')
        self.thread.start()

    def push(self, event):
        try:
            self.q.put_nowait(event)
        except queue.Full:
            self.log('Placar: fila de saidas cheia; evento descartado.')

    def _run(self):
        for sink in self.sinks:
            if isinstance(sink, DjangoSink) and sink.registration:
                try:
                    sink.register_room()
                except Exception as error:
                    self.log(f'Placar: registro de sala pendiente ({describe_error(error)}).')
        waiting = [s for s in self.sinks if isinstance(s, DjangoSink) and s.node]
        fixtures = [s for s in self.sinks if isinstance(s, FixtureResults)]
        while True:
            try:
                event = self.q.get(timeout=3 if waiting or fixtures else None)
            except queue.Empty:
                for sink in fixtures:
                    try:
                        sink.flush()
                    except (OSError, ValueError) as error:
                        self.log(f'Torneo: error al leer el resultado pendiente ({error}).')
                for sink in waiting.copy():
                    try:
                        if sink.refresh_players():
                            waiting.remove(sink)
                    except Exception as error:
                        if getattr(error, 'code', 0) in (401, 403, 404):
                            waiting.remove(sink)
                        self.log(f'Placar: consulta de jugadores pendiente ({describe_error(error)}).')
                continue
            if event is None:
                return
            for sink in self.sinks:
                try:
                    status = sink.send(event)
                    if isinstance(status, int):
                        self.log(f'Placar: resultado enviado ({sink.label}, HTTP {status}).')
                except Exception as error:                  # noqa: BLE001
                    # Nunca imprimir URL/token: webhooks sao segredos.
                    self.log(f'Placar: saida {sink.label} falhou ({describe_error(error)}).')

    def close(self, wait=3.0):
        self.q.put(None)
        self.thread.join(wait)


class FixtureResults:
    """Journal local detections and send them with the shared fight identity."""
    label = 'torneo'

    def __init__(self, args, log):
        self.url = args.api_url.rstrip('/')
        grant = args.fixture_result_grant
        self.session, self.ticket = grant['session'], grant['ticket']
        self.epoch_proof = grant.get('epoch_proof')
        self.epoch = args.session_epoch
        self.log = log
        scope = hashlib.sha256(f'{self.url}:{self.session}'.encode()).hexdigest()
        self.directory = appdata.DATA_DIR / 'fixture-results' / scope
        if getattr(args, 'cmd', '') == 'guest':
            self.directory = self.directory / 'p2'
        self.directory.mkdir(parents=True, exist_ok=True)
        series = grant['series']
        self.number = max([series['p1_wins'] + series['p2_wins']] +
                          [int(p.name.split('-')[0]) for p in self.directory.glob('[0-9]*-*.json')])
        self.finished = False
        self.last_error = None

    def record(self, event):
        entry = event.get('entry') or {}
        if (self.finished or entry.get('source') != 'memoria' or event['event'] != 'result'
                or entry.get('winner') not in ('p1', 'p2')):
            return
        number = entry.get('fight_number') if self.epoch_proof else self.number + 1
        if not number:
            self.log('Torneo: falta el número de pelea del detector.')
            return
        key = f'{self.epoch}-{number}'
        body = {'event': 'result', 'source': 'memoria', 'winner': entry['winner'], 'session': self.session,
                'match_number': number, 'idempotency_key': key, 'timestamp': entry['ts']}
        if self.epoch_proof:
            body['epoch_proof'] = self.epoch_proof
        if entry.get('chars'):
            body['characters'] = entry['chars']
        try:
            appdata.write_json(self.directory / f'{number:09d}-{key}.json', body, private=True)
        except OSError as error:
            self.log(f'Torneo: no se pudo guardar la victoria localmente ({error}).')
            return
        self.number = number

    def flush(self):
        from discord_auth import AccountError, api_call
        for path in sorted(self.directory.glob('[0-9]*-*.json')):
            body = json.loads(path.read_text(encoding='utf-8'))
            try:
                reply = api_call(self.url, 'POST', '/api/netplay/result/', body, token=self.ticket,
                                 extra_headers={'Idempotency-Key': body['idempotency_key']},
                                 timeout=5, follow_redirects=False)
                series = reply['series']
                if reply.get('status') != 'recorded' or reply.get('session') != self.session:
                    raise ValueError('respuesta sin confirmación del cruce')
            except (AccountError, KeyError, ValueError) as error:
                if getattr(error, 'code', None) == 409 and body.get('epoch_proof'):
                    self.log(f'Torneo: Django rechazó el resultado ({error}). Guardado para revisión.')
                    path.replace(path.with_suffix('.conflict'))
                    continue
                if str(error) != self.last_error:
                    self.log(f'Torneo: resultado pendiente de confirmación ({error}).')
                    self.last_error = str(error)
                return
            self.last_error = None
            self.finished = series['status'] == 'finished'
            path.unlink(missing_ok=True)
            self.log(f"Torneo: victoria de {body['winner'].upper()} confirmada. "
                     f"Marcador oficial {series['p1_wins']}–{series['p2_wins']}.")

    def send(self, event):
        self.flush()


class FileSink:
    label = 'arquivo'

    def __init__(self, cfg, board):
        self.board = board
        base = Path(cfg.get('dir') or appdata.DATA_DIR)
        base.mkdir(parents=True, exist_ok=True)
        self.text = base / cfg['text'] if cfg.get('text') else None
        self.json = base / cfg['json'] if cfg.get('json') else None
        self.send(None)                                     # arquivos existem desde o inicio (OBS ja le "J1: 0")

    def send(self, event):
        snap = self.board.snapshot()
        if self.text:
            self._write(self.text, snap['text'] + '\n')
        if self.json:
            self._write(self.json, json.dumps(snap, ensure_ascii=False, indent=2))

    @staticmethod
    def _write(path, text):
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)


class WebhookSink:
    label = 'webhook'

    def __init__(self, cfg, board):
        from urllib.parse import urlsplit
        self.board, self.cfg = board, cfg
        self.url = str(cfg.get('url') or '')
        if urlsplit(self.url).scheme not in ('http', 'https') or not urlsplit(self.url).hostname:
            raise ValueError('outputs.webhook.url debe ser una URL http(s)')

    def send(self, event):
        if event['event'] != 'result':
            return
        board = self.board
        text = board.render(self.cfg.get('message', '{format}').replace('{format}', board.cfg['format']))
        body = ({'content': text} if self.cfg.get('style', 'discord') == 'discord'
                else {'text': text, **{k: event[k] for k in ('p1', 'p2', 'draws', 'total', 'names', 'last')}})
        _post(self.url, body, self.cfg.get('headers') or {})


class DjangoSink:
    """Envia cada resultado ao site (rota e cabecalho configuraveis; padrao = contrato combinado com o servidor)."""
    label = 'django'

    def __init__(self, cfg, board, session='', registration=None, node=None, host_secret=None):
        from hill import validate_url
        self.url = (validate_url(cfg['url']).rstrip('/') + '/'
                    + cfg.get('path', '/api/netplay/casual/result/').lstrip('/'))
        envs = cfg.get('token_env') or []
        envs = [envs] if isinstance(envs, str) else envs
        self.token = cfg.get('token') or next((os.environ[e] for e in envs if os.environ.get(e)), '')
        self.registration = registration
        self.node = node
        self.host_secret = host_secret
        self.room_url = validate_url(cfg['url']).rstrip('/') + '/api/netplay/casual/rooms/'
        self.header = cfg.get('auth_header') or 'X-Netplay-Session'
        self.scheme = cfg.get('auth_scheme') or ''
        self.board, self.session = board, str(session or '')
        if not self.token:
            raise ValueError('falta a sessao do Netplay (entre com o Discord no launcher) ou outputs.django.token')

    def register_room(self):
        if self.registration:
            auth = f'{self.scheme} {self.token}' if self.scheme else self.token
            _post(self.room_url, self.registration, {self.header: auth})
            self.registration = None
            if self.node:
                self.node.score_secret = self.host_secret

    def refresh_players(self):
        if not self.node.score_secret:
            return False
        secret = self.node.score_secret.hex()
        session = hashlib.sha256(secret.encode()).hexdigest()[:32]
        headers = {self.header: f'{self.scheme} {self.token}'.strip()}
        if not self.node.is_host:
            headers['X-Casual-Guest'] = secret
        url = self.room_url.removesuffix('rooms/') + 'players/'
        data = _post(url, {'session': session}, headers, tries=1, timeout=3, read_json=True)
        players = data['players']
        with self.board.lock:
            self.board.players = players
        return bool(players['p1']['discord_id'] and players['p2']['discord_id'])

    def send(self, event):
        if event['event'] != 'result':
            return
        self.register_room()
        entry = event['entry']
        session = self.session
        number = entry['n']
        headers = {}
        if self.node:
            if entry['source'] != 'memoria':
                return
            number = entry.get('fight_number')
            if not number or not self.node.score_secret:
                return
            if not self.node.is_host:
                secret = self.node.score_secret.hex()
                session = hashlib.sha256(secret.encode()).hexdigest()[:32]
                headers['X-Casual-Guest'] = secret
        key = (f'{session}-{number}' if session else
               hashlib.sha256(f"{number}:{entry['ts']:.3f}".encode()).hexdigest()[:24])
        body = {'event': 'result', 'winner': entry['winner'], 'source': entry['source'],
                'score': {'p1': event['p1'], 'p2': event['p2'], 'draws': event['draws']},
                'names': event['names'], 'match_number': number, 'session': session,
                'idempotency_key': key, 'timestamp': entry['ts']}
        if entry.get('chars') is not None:
            body['characters'] = entry['chars']
        auth = f'{self.scheme} {self.token}' if self.scheme else self.token
        return _post(self.url, body, {self.header: auth, 'Idempotency-Key': key, **headers})


def describe_error(error):
    """Texto curto do erro para o log: codigo HTTP e a mensagem do servidor, nunca a URL nem os cabecalhos."""
    code = getattr(error, 'code', None)
    if isinstance(code, int):
        detail = ''
        try:
            data = json.loads(error.read(2048).decode('utf-8', 'replace'))
            detail = data.get('detail') or data.get('error') or json.dumps(data, ensure_ascii=False)
        except Exception:                                   # noqa: BLE001
            pass
        return f'HTTP {code}' + (f': {str(detail)[:200]}' if detail else '')
    reason = getattr(error, 'reason', None)
    return f'{type(error).__name__}: {type(reason).__name__ if reason is not None else ""}'.rstrip(': ')


def _post(url, body, headers, tries=3, timeout=6, read_json=False):
    """POST JSON com 3 tentativas (rede instavel). Erros 4xx nao sao repetidos."""
    import ssl
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlsplit
    from urllib.request import Request, urlopen
    from discord_auth import UA, ssl_context
    request = Request(url, data=json.dumps(body).encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'User-Agent': UA, **headers})
    target = urlsplit(url)
    last = None
    for attempt in range(tries):
        try:
            context = ssl_context(target.hostname) if target.scheme == 'https' else None
            with urlopen(request, timeout=timeout, context=context) as response:
                if read_json:
                    return json.loads(response.read(4096))
                response.read(256)
                return response.status
        except HTTPError as error:
            last = error
            if 400 <= error.code < 500 and error.code != 429:
                raise
        except (URLError, OSError, ssl.SSLError) as error:
            last = error
        time.sleep(0.5 * (attempt + 1))
    raise last


# ---------------------------------------------------------------------------------------------------------------
def ws_frame(text):
    payload = text.encode('utf-8')
    n = len(payload)
    head = b'\x81' + (bytes([n]) if n < 126 else b'\x7e' + struct.pack('>H', n) if n < 65536
                      else b'\x7f' + struct.pack('>Q', n))
    return head + payload


class HttpSink:
    """API local: GET /score, GET /text, WebSocket em /ws (envia o placar ao conectar e a cada mudanca).
    Com `token`: POST /score/p1|p2|draw|undo|reset (cabecalho Authorization: Bearer ...)."""
    label = 'http'

    def __init__(self, cfg, board):
        self.board, self.token = board, str(cfg.get('token') or '')
        self.clients, self.clients_lock = [], threading.Lock()
        sink = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def _send(self, code, body, ctype='application/json'):
                data = body if isinstance(body, bytes) else body.encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', ctype + '; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split('?')[0]
                if path == '/score':
                    self._send(200, json.dumps(sink.board.snapshot(), ensure_ascii=False))
                elif path == '/text':
                    self._send(200, sink.board.render(), 'text/plain')
                elif path == '/ws' and self.headers.get('Upgrade', '').lower() == 'websocket':
                    key = self.headers.get('Sec-WebSocket-Key', '')
                    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
                    self.wfile.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                                      f'Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n').encode())
                    self.wfile.flush()
                    sink._add(self.connection)
                    self.close_connection = True
                    try:                                # o envio e feito por send(); aqui so esperamos o fechamento
                        while self.connection.recv(1024):
                            pass
                    except OSError:
                        pass
                    sink._drop(self.connection)
                else:
                    self._send(404, '{"error":"not found"}')

            def do_POST(self):
                path = self.path.split('?')[0]
                supplied = self.headers.get('Authorization', '')
                if not sink.token or supplied != 'Bearer ' + sink.token or self.headers.get('Origin'):
                    return self._send(403, '{"error":"forbidden"}')
                action = path.rsplit('/', 1)[-1]
                if not path.startswith('/score/'):
                    return self._send(404, '{"error":"not found"}')
                if action in WINNERS:
                    sink.board.record(action, 'api')
                elif action == 'undo':
                    sink.board.undo()
                elif action == 'reset':
                    sink.board.reset()
                else:
                    return self._send(404, '{"error":"not found"}')
                self._send(200, json.dumps(sink.board.snapshot(), ensure_ascii=False))

        host = cfg.get('host') or '127.0.0.1'
        self.server = ThreadingHTTPServer((host, int(cfg.get('port', 47500))), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True, name='scoreboard-http').start()

    def _add(self, conn):
        with self.clients_lock:
            self.clients.append(conn)
        self._broadcast_one(conn, json.dumps({'event': 'hello', **self.board.snapshot()}, ensure_ascii=False))

    def _drop(self, conn):
        with self.clients_lock:
            if conn in self.clients:
                self.clients.remove(conn)

    def _broadcast_one(self, conn, text):
        try:
            conn.sendall(ws_frame(text))
            return True
        except OSError:
            return False

    def send(self, event):
        text = json.dumps(event, ensure_ascii=False)
        with self.clients_lock:
            self.clients = [c for c in self.clients if self._broadcast_one(c, text)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


# ---------------------------------------------------------------------------------------------------------------
class ScoreboardService:
    """Junta tudo para uma sessao de netplay. `tick()` vai dentro do loop principal; `close()` no final."""

    def __init__(self, board, dispatcher, detector, sinks):
        self.score_host = None
        self.board, self.dispatcher, self.detector, self.sinks = board, dispatcher, detector, sinks

    def tick(self):
        self.detector.tick()
        if self.score_host:
            self.score_host.score_round = self.detector.fight_number

    def set_nicks(self, names):
        if names and len(names) >= 2:
            self.board.set_nicks(names[0], names[1])

    def close(self):
        self.dispatcher.close()
        for sink in self.sinks:
            if hasattr(sink, 'close'):
                try:
                    sink.close()
                except Exception:                            # noqa: BLE001
                    pass


def profile_config(cfg, serial, crc=''):
    """Aplica o perfil do jogo sobre a configuracao. A chave pode ser 'SERIAL:CRC' (uma build especifica, ex.
    mods diferentes com o mesmo serial) ou so 'SERIAL'; a mais especifica ganha. '-' e '_' sao ignorados."""
    norm = lambda x: ''.join(c for c in str(x).upper() if c.isalnum())
    found = {}
    for key, profile in (cfg.get('profiles') or {}).items():
        if isinstance(profile, dict):
            found[tuple(norm(part) for part in str(key).split(':', 1))] = profile
    for wanted in ((norm(serial), norm(crc)), (norm(serial),)):
        if wanted in found and (len(wanted) == 1 or wanted[1]):
            return merge(cfg, found[wanted])
    return cfg


def build(cfg, read=None, is_host=True, session='', log=print, state_path=None, serial='', crc='', registration=None, node=None, host_secret=None, fixture_sink=None):
    """Monta o servico a partir da configuracao. Devolve None se estiver desligado."""
    if not cfg.get('enabled'):
        return None
    cfg = profile_config(cfg, serial, crc)
    board = Scoreboard(cfg, state_path or appdata.DATA_DIR / STATE_NAME)
    out, sinks = cfg['outputs'], []

    def add(name, factory, external=False):
        spec = out.get(name) or {}
        if not spec.get('enabled'):
            return
        if external and cfg.get('external_only_host') and not is_host:
            return
        try:
            sinks.append(factory(spec))
        except (OSError, ValueError, KeyError) as error:
            log(f'Placar: saida {name} desactivada ({error}).')

    add('file', lambda s: FileSink(s, board))
    add('http', lambda s: HttpSink(s, board))
    add('webhook', lambda s: WebhookSink(s, board), external=True)
    if is_host or node:
        add('django', lambda spec: DjangoSink(spec, board, session, registration, node, host_secret))
    if fixture_sink:
        sinks.insert(0, fixture_sink)
        board.listeners.append(fixture_sink.record)
    dispatcher = Dispatcher(sinks, log)
    board.listeners.append(dispatcher.push)
    def record(who, chars=None):
        number = detector.fight_number if fixture_sink and fixture_sink.epoch_proof else None
        if node:
            number = detector.fight_number
            if not is_host and (not node.score_secret or node.score_round != number):
                number = 0
                log('Placar: P2 sin confirmación de la sala y pelea de P1; resultado solo local.')
        log(_result_line(board.record(who, 'memoria', chars, number)))

    detector = make_detector(cfg.get('detector') or {}, read or (lambda addr, size: 0), record)
    if not detector.active:
        log(f'Placar activo; sin detector para este juego ({serial or "serial desconocido"} {crc}): solo manual / API.')
    for sink in sinks:
        if isinstance(sink, HttpSink):
            log(f'Placar: API local en http://{out["http"].get("host", "127.0.0.1")}:{sink.port}/score')
    service = ScoreboardService(board, dispatcher, detector, sinks)
    service.score_host = node if is_host else None
    return service


def _result_line(event):
    chars = (event.get('entry') or {}).get('chars') or {}
    who = {'p1': 'P1', 'p2': 'P2', 'draw': 'empate'}[event['entry']['winner']]
    vs = f" ({chars['p1']['name']} vs {chars['p2']['name']})" if chars else ''
    return f"Placar: {event['text']}  - vencedor: {who}{vs}"


def session_id(args, room=''):
    """Identificador da partida enviado ao servidor: o session_epoch / round_id do KOTH; nas partidas casuais
    (session_epoch = '0') o ID da sala. Vazio se nao houver nenhum dos dois."""
    epoch = str(getattr(args, 'session_epoch', '') or '').strip()
    if epoch and epoch != '0':
        return epoch
    return str(room or getattr(args, 'room', '') or '').strip()


def online_config(cfg, online):
    """Partida casual pela rede do Netplay com sessao de Discord: liga placar + envio ao site (se auto_online)."""
    envs = cfg['outputs']['django'].get('token_env') or []
    envs = [envs] if isinstance(envs, str) else envs
    has_session = bool(cfg['outputs']['django'].get('token')) or any(os.environ.get(e) for e in envs)
    if not (online and cfg.get('auto_online') and has_session):
        return cfg
    url = cfg['outputs']['django'].get('url') or cfg.get('site_url') or ''
    return merge(cfg, {'enabled': True, 'outputs': {'django': {'enabled': True, 'url': url}}})


def file_logger(log, path=None):
    """Imprime e tambem anexa a scoreboard.log (pasta de dados), para conferir depois de uma partida."""
    path = Path(path) if path else appdata.DATA_DIR / 'scoreboard.log'

    def write(message):
        log(message)
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            pass
    return write


def koth_reporter(path, session):
    """Publish the first detected victory; the KOTH coordinator owns the ticket."""
    reported = False

    def record(event):
        nonlocal reported
        entry = event.get('entry') or {}
        if reported or event['event'] != 'result' or entry.get('source') != 'memoria' or entry['winner'] not in ('p1', 'p2'):
            return
        payload = {'event': 'result', 'winner': entry['winner'], 'source': 'memoria',
                   'match_number': entry['n'], 'session': session, 'idempotency_key': session + '-win',
                   'timestamp': entry['ts'], 'names': event['names'],
                   'score': {key: event[key] for key in ('p1', 'p2', 'draws')}}
        if entry.get('chars'):
            payload['characters'] = entry['chars']
        appdata.write_json(path, payload, private=True)
        reported = True

    return record


def start_for_session(args, pine, is_host, log=print, room='', online=False, node=None):
    """Gancho do netplay: devuelve el servicio o None. Nunca lanza."""
    log = file_logger(log)
    try:
        casual = str(getattr(args, 'session_epoch', '0') or '0') == '0'
        zerotier = not online and (getattr(args, 'zerotier', False) or
                                   getattr(args, 'bind_address', '0.0.0.0') not in ('', '0.0.0.0'))
        cfg = online_config(load_config(getattr(args, 'scoreboard_config', None)),
                            casual and (online or zerotier))
        report_path = os.environ.get('UN5_KOTH_RESULT_FILE') if not casual else None
        fixture = getattr(args, 'tournament_fixture', None)
        fixture_sink = FixtureResults(args, log) if fixture and getattr(args, 'fixture_result_grant', None) else None
        if not casual:
            cfg = merge(cfg, {'enabled': bool(fixture or report_path or cfg['enabled']),
                              'outputs': {'django': {'enabled': False}}})
        serial = crc = ''
        try:
            serial = pine.game_id()
            crc = pine.game_crc()
        except Exception:                                    # noqa: BLE001 - sin serial/CRC se usa `detector`
            pass
        session = session_id(args, room)
        registration = None
        django = cfg['outputs']['django']
        shared = (casual and (online or zerotier) and django.get('enabled')
                  and django.get('path') == '/api/netplay/casual/result/')
        score_node = node if shared else None
        host_secret = None
        if score_node and not is_host:
            score_node.score_challenge = os.urandom(16)
        if shared and is_host:
            session = uuid.uuid4().hex
            registration = {'session': session, 'transport': 'netplay' if online else 'zerotier',
                            'network_room': str(room or '')}
            if score_node:
                host_secret = os.urandom(16)
                session = hashlib.sha256(host_secret.hex().encode()).hexdigest()[:32]
                registration.update(session=session, dual_report=True)
        log(f'Placar: juego {serial} {crc}, {"host" if is_host else "guest"}, partida {session or "?"}, '
            f'{"online" if online else "directa"}, activo={bool(cfg.get("enabled"))}.')
        service = build(cfg, lambda addr, size: pine.read(addr, size), is_host, session, log, serial=serial, crc=crc, registration=registration,
                        node=score_node, host_secret=host_secret, fixture_sink=fixture_sink)
        if service and report_path:
            service.board.players = json.loads(os.environ.get('UN5_KOTH_PLAYERS') or '{}')
            service.board.listeners.append(koth_reporter(Path(report_path), session))
        if service and any(isinstance(x, DjangoSink) for x in service.sinks):
            log(f'Placar: resultados se enviarán a {cfg["outputs"]["django"]["url"]} (partida {session or "?"}).')
        return service
    except Exception as error:                               # noqa: BLE001 - el placar nunca bloquea la pelea
        log(f'Placar desactivado: {error}')
        return None


# ---------------------------------------------------------------------------------------------------------------
def _probe(args):
    from pine import Pine
    start, end = int(args.start, 0), int(args.end, 0)
    if end <= start or (end - start) % 4 or (end - start) > 0x40000:
        raise SystemExit('Rango invalido: end > start, multiplo de 4 y como maximo 256 KB.')
    pine = Pine(args.pine_slot).connect()
    data = bytearray()
    for base in range(start, end, 4 * 256):
        words = pine.batch([('r', a, 4) for a in range(base, min(end, base + 4 * 256), 4)])
        for w in words:
            data += struct.pack('<I', w)
    pine.close()
    Path(args.out).write_bytes(bytes(data))
    print(f'{len(data)} bytes de {start:#x} a {end:#x} guardados en {args.out}')


def _watch(args):
    from pine import Pine
    pine = Pine(args.pine_slot).connect()
    serial, crc = pine.game_id(), pine.game_crc()
    cfg = load_config()
    cfg['enabled'] = True
    service = build(cfg, lambda addr, size: pine.read(addr, size), True, 'watch', serial=serial, crc=crc)
    print(f'Juego {serial} {crc}. Marcador: {service.board.render()}  (Ctrl+C para salir)', flush=True)
    if hasattr(service.detector, 'on_status'):
        fmt = lambda v: '-' if v is None else hex(v)
        service.detector.on_status = lambda a, b, hp: print(
            f'  status {fmt(a)} -> {fmt(b)}  vida={None if hp is None else tuple(round(x, 3) for x in hp)}', flush=True)
    try:
        while True:
            service.tick()
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        pine.close()


def _diff(args):
    """Direcciones (bytes) cuyo valor es igual en las capturas de un mismo resultado y distinto entre resultados."""
    start = int(args.start, 0)
    groups = {}
    for spec in args.captures:                               # etiqueta=archivo, p. ej. p1=a.bin p1=b.bin p2=c.bin
        label, _, path = spec.partition('=')
        groups.setdefault(label, []).append(Path(path).read_bytes())
    if len(groups) < 2:
        raise SystemExit('Pasa al menos dos etiquetas, p. ej. p1=a.bin p2=b.bin')
    size = min(len(d) for g in groups.values() for d in g)
    labels = sorted(groups)
    shown = 0
    for i in range(size):
        values = {}
        for label in labels:
            seen = {d[i] for d in groups[label]}
            if len(seen) != 1:
                break
            values[label] = seen.pop()
        else:
            if len(set(values.values())) == len(labels):
                print(f"{start + i:#010x}  " + '  '.join(f'{k}={v:#04x}' for k, v in values.items()))
                shown += 1
                if shown >= args.limit:
                    print('... (limite alcanzado)')
                    return
    print(f'{shown} candidatos.')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('init', help='crea scoreboard.json con los valores por defecto')
    sub.add_parser('show', help='muestra la configuracion efectiva')
    t = sub.add_parser('test', help='registra un resultado de prueba en todas las salidas (sin juego)')
    t.add_argument('winner', choices=WINNERS)
    w = sub.add_parser('watch', help='corre el marcador contra el PCSX2 abierto, sin netplay (Ctrl+C para salir)')
    w.add_argument('--pine-slot', type=int, default=28011)
    p = sub.add_parser('probe', help='guarda un rango de RAM de PCSX2 (para encontrar el resultado)')
    p.add_argument('--start', required=True)
    p.add_argument('--end', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--pine-slot', type=int, default=28011)
    d = sub.add_parser('diff', help='compara capturas etiquetadas: direcciones que distinguen p1/p2/draw')
    d.add_argument('--start', required=True, help='direccion inicial usada en probe')
    d.add_argument('--limit', type=int, default=200)
    d.add_argument('captures', nargs='+', metavar='etiqueta=archivo')
    args = ap.parse_args(argv)
    if args.cmd == 'init':
        path = config_path()
        if path.exists():
            raise SystemExit(f'{path} ya existe; no se sobrescribe.')
        appdata.write_json(path, DEFAULTS)
        print(f'Creado {path}')
    elif args.cmd == 'show':
        print(f'# {config_path()}')
        print(json.dumps(load_config(), indent=2, ensure_ascii=False))
    elif args.cmd == 'test':
        cfg = load_config()
        cfg['enabled'] = True
        service = build(cfg, is_host=True, session='test')
        print(service.board.record(args.winner, 'test')['text'])
        service.close()
    elif args.cmd == 'watch':
        _watch(args)
    elif args.cmd == 'probe':
        _probe(args)
    else:
        _diff(args)


if __name__ == '__main__':
    sys.exit(main())
