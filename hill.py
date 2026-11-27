"""Django-coordinated King of the Hill using direct netplay over ZeroTier."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import ssl
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class HillError(Exception):
    pass


def file_tag(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Indica la URL base de Django, por ejemplo https://torneos.example.com')
    return url.rstrip('/')


def sync(url, ticket, body, *, observe=False):
    path = '/api/netplay/watch/sync/' if observe else '/api/netplay/sync/'
    request = Request(url + path, data=json.dumps(body).encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + ticket})
    from discord_auth import ssl_context

    try:
        target = urlsplit(url)
        context = ssl_context(target.hostname) if target.scheme == 'https' else None
        with urlopen(request, timeout=4, context=context) as response:
            snapshot = json.load(response)
        if not isinstance(snapshot, dict):
            raise ValueError('Se esperaba un objeto JSON.')
        return snapshot
    except HTTPError as error:
        # Never include the request or ticket in output.
        if error.code in (401, 403):
            if observe:
                raise HillError('Código de observador inválido o vencido. Vuelve a abrir el evento.') from None
            raise HillError('Código KOTH inactivo o inválido. Comprueba tu inscripción y el estado del evento.') from None
        if error.code == 400:
            raise HillError('Django rechazó la configuración de netplay. Comprueba la IP y el torneo.') from None
        raise OSError(f'Django respondió HTTP {error.code}.') from None
    except (URLError, OSError, ValueError) as error:
        reason = error.reason if isinstance(error, URLError) else error
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = 'falló la validación del certificado HTTPS'
        elif isinstance(reason, ssl.SSLError):
            detail = 'falló la conexión TLS'
        elif isinstance(reason, socket.gaierror):
            detail = 'no se pudo resolver el dominio (DNS)'
        elif isinstance(reason, TimeoutError):
            detail = 'se agotó el tiempo de espera'
        elif isinstance(reason, ValueError):
            detail = 'la respuesta no contiene un JSON válido'
        else:
            detail = 'falló la conexión de red'
        raise OSError(f'No se pudo consultar Django ({detail}).') from None


def round_nick(snapshot, fallback):
    role = snapshot.get('role')
    if role in ('host', 'guest'):
        slot = 'p1' if role == 'host' else 'p2'
        player = (snapshot.get('players') or {}).get(slot) or {}
        current = (snapshot.get('event') or {}).get('current_match') or {}
        return player.get('name') or (current.get('player1' if role == 'host' else 'player2') or {}).get('name') or fallback
    return fallback


def round_scores(snapshot):
    current = (snapshot.get('event') or {}).get('current_match') or {}
    players = snapshot.get('players') or {}
    return [(current.get(key) or {}).get('points', (players.get(slot) or {}).get('points'))
            for slot, key in (('p1', 'player1'), ('p2', 'player2'))]


def waiting_reason(snapshot):
    reason = snapshot['reason']
    if snapshot['ready'] or reason != 'Esperando a los dos jugadores de la pareja.':
        return reason
    role = snapshot['role']
    # Django only exposes the guest endpoint to the host.
    if role == 'host' and snapshot.get('host') and 'guest' in snapshot and not snapshot['guest']:
        missing, label = 'player2', 'P2'
    elif role == 'guest' and 'host' in snapshot and not snapshot['host']:
        missing, label = 'player1', 'P1'
    else:
        return reason
    match = (snapshot.get('event') or {}).get('current_match') or {}
    name = (match.get(missing) or {}).get('name')
    player = f'{label} ({name})' if name else label
    return f'Esperando que el launcher de {player} esté disponible para esta ronda de Rey de la Colina.'


def match_command(args, snapshot, stop_file):
    host = snapshot['host']
    role = 'watch' if snapshot['role'] == 'spectator' else snapshot['role']
    command = [sys.executable, '-u', str(Path(__file__).with_name('netplay.py')),
               '--symbols', args.symbols, '--pine-slot', str(args.pine_slot), '--stop-file', str(stop_file),
               role, '--state', args.state, '--state-dir', args.state_dir, '--load-slot', str(args.load_slot),
               '--delay', str((args.delay or 3) if role == 'host' else host['delay']), '--nick', round_nick(snapshot, args.nick)]
    if role == 'host' and (getattr(args, 'auto_delay', False) or not args.delay):
        command.append('--auto-delay')
    if snapshot.get('session_epoch') or snapshot.get('round_id'):
        command += ['--session-epoch', str(snapshot.get('session_epoch') or snapshot['round_id'])]
    if args.stop_file:
        command[3:3] = ['--parent-stop-file', str(args.stop_file)]
    if role == 'host':
        command += ['--server', '', '--bind-address', args.address]
        if (snapshot.get('guest') or {}).get('address'):
            command += ['--expect-guest-ip', snapshot['guest']['address']]
        command += ['--port', str(args.port), '--no-announce', '--no-share-state']
    elif role == 'guest':
        command += ['--server', '', '--bind-address', args.address, '--connect', f"{host['address']}:{host['port']}"]
    else:
        command += ['--server', '', '--connect', f"{host['address']}:{host['spectator_port']}"]
    if role in ('host', 'guest') and snapshot.get('spectator_key') and not getattr(args, 'no_spectators', False):
        command += ['--spectator-port', str(args.port+1)]
    return command


def stop_match(process, stop_file):
    if process is None:
        return
    Path(stop_file).touch()
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def prepare_waiting(args):
    from netplay import load_match_state
    return load_match_state(args)


def release_game(args):
    from netplay import connect
    pine, core = connect(args)
    try:
        core.put('hold', 0)
        core.stop()
    finally:
        pine.close()


def submit_pending_result(path, url, ticket):
    from discord_auth import AccountError, api_call
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding='utf-8'))
    try:
        result = api_call(url, 'POST', '/api/netplay/result/', payload, token=ticket, timeout=4,
                          extra_headers={'Idempotency-Key': payload['idempotency_key']}, follow_redirects=False)
    except AccountError as error:
        print(f'KOTH: envío de resultado: {error}', flush=True)
        if error.code == 0 or error.code == 429 or error.code >= 500:
            return
    else:
        print(f"KOTH: victoria registrada por Django (partida {result.get('match_id')}).", flush=True)
    path.unlink(missing_ok=True)


def run(args):
    url = validate_url(args.api_url)
    observe = getattr(args, 'observe', False)
    address = ipaddress.IPv4Address(args.address)
    if address.is_loopback or address.is_multicast or address.is_unspecified:
        raise ValueError('Introduce la IPv4 de ZeroTier de este PC.')
    ticket = os.environ.get('UN5_HILL_TICKET', '').strip()
    if not ticket:
        if observe:
            raise ValueError('Falta el código de observador. Abre el evento desde Netplay.')
        raise ValueError('Falta UN5_HILL_TICKET: genera el código personal desde el torneo.')
    body = {'address': str(address), 'port': args.port, 'game': args.game, 'delay': args.delay or 3,
            'state_tag': file_tag(args.state), 'symbols_tag': file_tag(args.symbols), 'available': True,
            'transport': 'zerotier', 'spectators_enabled': observe or not getattr(args, 'no_spectators', False)}
    if getattr(args, 'personal_code', False):
        body['personal_code'] = True
    process, active_round, blocked_round, last_message = None, None, None, None
    active_role, watch_failed_round = None, None
    active_stream, watch_retry_at = None, 0
    last_board = None
    registered = False
    with tempfile.TemporaryDirectory(prefix='un5-hill-') as directory:
        child_stop = Path(directory) / 'stop'
        result_file = Path(directory) / 'result.json'
        try:
            print('Rey de la colina: cargando el save state en PCSX2 para observar ...' if observe else
                  'Rey de la colina: cargando el save state en PCSX2 antes de entrar a la cola ...', flush=True)
            if not prepare_waiting(args):
                if args.stop_file and Path(args.stop_file).exists():
                    return 0
                raise HillError('No se pudo cargar y congelar el save state. No se anunció al jugador como listo.')
            print('Estado cargado y congelado. Conectando a Django.', flush=True)
            last_success = time.monotonic()
            while not (args.stop_file and Path(args.stop_file).exists()):
                submit_pending_result(result_file, url, ticket)
                if process is not None and process.poll() is not None:
                    if active_role == 'spectator':
                        watch_failed_round = active_round
                        watch_retry_at = time.monotonic()+5
                        print('La transmisión terminó. Se recargará el estado y se buscará otra fuente en 5 segundos. Sigues disponible para tu turno.', flush=True)
                    else:
                        blocked_round = active_round
                        print('La sesión terminó. Esperando que Django actualice la ronda.', flush=True)
                    process = None
                body['available'] = blocked_round is None
                try:
                    if observe:
                        snapshot = sync(url, ticket, dict(body), observe=True)
                        if snapshot.get('role') not in (None, 'spectator'):
                            raise HillError('Django devolvió un rol incompatible con el modo observador.')
                    else:
                        snapshot = sync(url, ticket, dict(body))
                    if snapshot.get('transport') != 'zerotier':
                        raise HillError('Actualiza Django y los dos launchers: la pareja debe usar el mismo transporte de KOTH.')
                    registered = True
                    last_success = time.monotonic()
                except OSError as error:
                    print(str(error), flush=True)
                    if time.monotonic() - last_success >= 12:
                        raise HillError('Se perdió la conexión con Django. Se detuvo el combate; vuelve a conectar.') from None
                else:
                    reason = waiting_reason(snapshot)
                    if isinstance(snapshot.get('event'), dict):
                        board = json.dumps({**{key: snapshot.get(key) for key in ('event', 'role', 'ready')},
                                            'reason': reason},
                                           ensure_ascii=True, sort_keys=True)
                        if board != last_board:
                            print('KOTH_STATE ' + board, flush=True)
                            last_board = board
                    round_id = snapshot['round_id']
                    stream_id = snapshot.get('stream_id') or round_id
                    if blocked_round is not None and round_id != blocked_round:
                        blocked_round = None
                        # Publish availability for the new pair before starting it.
                        continue
                    if watch_failed_round is not None and round_id != watch_failed_round:
                        watch_failed_round = None
                    if process is not None and (round_id != active_round or snapshot['role'] != active_role or not snapshot['ready']
                                                or (active_role == 'spectator' and stream_id != active_stream)):
                        stop_match(process, child_stop)
                        process = None
                        if round_id == active_round and active_role != 'spectator':
                            blocked_round = active_round
                    if snapshot['status'] == 'finished':
                        print('El torneo finalizó.', flush=True)
                        return 0
                    message = (' | '.join(f"{i+1}. {p['name']} ({p['points']} pts)" for i, p in enumerate(snapshot['queue'])),
                               snapshot['role'], reason)
                    if message != last_message:
                        print('Cola: ' + message[0], flush=True)
                        print(f"Turno: {snapshot['role'] or 'en espera'}. {reason}", flush=True)
                        last_message = message
                    watching_failed = (snapshot['role'] == 'spectator' and watch_failed_round == round_id
                                       and time.monotonic() < watch_retry_at)
                    watching_disabled = not observe and snapshot['role'] == 'spectator' and getattr(args, 'no_spectators', False)
                    if process is None and blocked_round is None and snapshot['ready'] and not watching_failed and not watching_disabled:
                        child_stop.unlink(missing_ok=True)
                        active_round = round_id
                        active_stream = stream_id
                        active_role = snapshot['role']
                        print('Iniciando modo espectador.' if active_role == 'spectator' else f"Iniciando combate como {active_role}.", flush=True)
                        child_env = os.environ.copy()
                        child_env.pop('UN5_HILL_TICKET', None)
                        child_env.pop('UN5_KOTH_RESULT_FILE', None)
                        child_env.pop('UN5_KOTH_OVERLAY_SCORES', None)
                        if active_role in ('host', 'guest'):
                            child_env['UN5_KOTH_PLAYERS'] = json.dumps(snapshot.get('players') or {})
                            child_env['UN5_KOTH_OVERLAY_SCORES'] = json.dumps(round_scores(snapshot))
                            child_env['UN5_KOTH_RESULT_FILE'] = str(result_file)
                        if active_role == 'spectator':
                            child_env.pop('UN5_NETPLAY_SESSION', None)
                            child_env['UN5_SPECTATOR_SOURCES'] = json.dumps(snapshot.get('spectator_sources') or [])
                        else:
                            child_env.pop('UN5_SPECTATOR_SOURCES', None)
                        if snapshot.get('spectator_key'):
                            child_env['UN5_SPECTATOR_KEY'] = snapshot['spectator_key']
                        else:
                            child_env.pop('UN5_SPECTATOR_KEY', None)
                        process = subprocess.Popen(match_command(args, snapshot, child_stop), env=child_env)
                # Remain responsive to STOP while waiting between heartbeats.
                for _ in range(20):
                    if args.stop_file and Path(args.stop_file).exists():
                        break
                    time.sleep(0.1)
        finally:
            stop_match(process, child_stop)
            if not observe:
                submit_pending_result(result_file, url, ticket)
            try:
                release_game(args)
            except Exception as error:
                print(f'No se pudo liberar PCSX2 al salir de KOTH: {error}', flush=True)
            try:
                if registered and not observe:
                    sync(url, ticket, {**body, 'offline': True})
            except (OSError, HillError):
                pass
    return 0


def command(args):
    try:
        return run(args)
    except (OSError, ValueError, HillError) as error:
        print(f'Rey de la colina: {error}', flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
