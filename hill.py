"""Django-coordinated King of the Hill using direct netplay over ZeroTier."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
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


def sync(url, ticket, body):
    request = Request(url + '/api/netplay/sync/', data=json.dumps(body).encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + ticket})
    try:
        with urlopen(request, timeout=4) as response:
            return json.load(response)
    except HTTPError as error:
        # Never include the request or ticket in output.
        if error.code in (401, 403):
            raise HillError('Código inválido o vencido. Genera uno nuevo desde el torneo.') from None
        if error.code == 400:
            raise HillError('Django rechazó la configuración de netplay. Comprueba la IP y el torneo.') from None
        raise OSError(f'Django respondió HTTP {error.code}.') from None
    except (URLError, ValueError) as error:
        raise OSError('No se pudo consultar Django.') from None


def match_command(args, snapshot, stop_file, room_file=None):
    import netlink
    host = snapshot['host']
    role = 'watch' if snapshot['role'] == 'spectator' else snapshot['role']
    transport = getattr(args, 'transport', 'zerotier')
    command = [sys.executable, '-u', str(Path(__file__).with_name('netplay.py')),
               '--symbols', args.symbols, '--pine-slot', str(args.pine_slot), '--stop-file', str(stop_file),
               role, '--state', args.state, '--state-dir', args.state_dir, '--load-slot', str(args.load_slot),
               '--delay', str(args.delay if role == 'host' else host['delay']), '--nick', args.nick]
    if snapshot.get('session_epoch') or snapshot.get('round_id'):
        command += ['--session-epoch', str(snapshot.get('session_epoch') or snapshot['round_id'])]
    if args.stop_file:
        command[3:3] = ['--parent-stop-file', str(args.stop_file)]
    if role == 'host':
        if transport == 'relay':
            command += ['--server', getattr(args, 'relay_server', netlink.DEFAULT_SERVER),
                        '--api-url', getattr(args, 'relay_api_url', netlink.DEFAULT_API_URL), '--relay-only']
        else:
            command += ['--server', '']
            if (snapshot.get('guest') or {}).get('address'):
                command += ['--expect-guest-ip', snapshot['guest']['address']]
        command += ['--port', str(args.port), '--no-announce', '--no-share-state']
        if room_file is not None and transport == 'relay':
            command += ['--room-file', str(room_file)]
        if snapshot.get('spectator_key') and not getattr(args, 'no_spectators', False):
            command += ['--spectator-port', str(host['spectator_port'])]
    elif role == 'guest':
        if transport == 'relay':
            if not host.get('relay_room'):
                raise HillError('La sala del servidor principal todavía no está lista.')
            command += ['--server', getattr(args, 'relay_server', netlink.DEFAULT_SERVER),
                        '--api-url', getattr(args, 'relay_api_url', netlink.DEFAULT_API_URL),
                        '--relay-only', '--room', host['relay_room'], '--fetch-state', '--bind-port', '0']
        else:
            command += ['--server', '', '--connect', f"{host['address']}:{host['port']}", '--bind-port', '0']
    else:
        command += ['--server', '', '--connect', f"{host['address']}:{host['spectator_port']}"]
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


def run(args):
    url = validate_url(args.api_url)
    address = ipaddress.IPv4Address(args.address)
    transport = getattr(args, 'transport', 'zerotier')
    if address.is_loopback or address.is_multicast or (transport == 'zerotier' and address.is_unspecified):
        raise ValueError('Introduce la IPv4 de ZeroTier de este PC.')
    ticket = os.environ.get('UN5_HILL_TICKET', '').strip()
    if not ticket:
        raise ValueError('Falta UN5_HILL_TICKET: genera el código personal desde el torneo.')
    body = {'address': str(address), 'port': args.port, 'game': args.game, 'delay': args.delay or 3,
            'state_tag': file_tag(args.state), 'symbols_tag': file_tag(args.symbols), 'available': True,
            'transport': transport, 'spectators_enabled': not getattr(args, 'no_spectators', False)}
    process, active_round, blocked_round, last_message = None, None, None, None
    active_role, watch_failed_round = None, None
    last_board = None
    registered = False
    with tempfile.TemporaryDirectory(prefix='un5-hill-') as directory:
        child_stop = Path(directory) / 'stop'
        room_file = Path(directory) / 'room.json'
        try:
            print('Rey de la colina: cargando el save state en PCSX2 antes de entrar a la cola ...', flush=True)
            if not prepare_waiting(args):
                if args.stop_file and Path(args.stop_file).exists():
                    return 0
                raise HillError('No se pudo cargar y congelar el save state. No se anunció al jugador como listo.')
            print('Estado cargado y congelado. Conectando a Django; resultados desde el panel del torneo.', flush=True)
            last_success = time.monotonic()
            while not (args.stop_file and Path(args.stop_file).exists()):
                if process is not None and process.poll() is not None:
                    if active_role == 'spectator':
                        watch_failed_round = active_round
                        print('La transmisión terminó. Sigues disponible para tu turno; puedes reentrar a KOTH para volver a observar.', flush=True)
                    else:
                        blocked_round = active_round
                        print('La sesión terminó. Esperando el resultado del organizador; reinicia este modo para reintentar.', flush=True)
                    process = None
                body['available'] = blocked_round is None
                body['room_id'], body['room_round'] = '', ''
                body['delay'] = args.delay or 3
                if transport == 'relay' and process is not None and active_role == 'host' and room_file.is_file():
                    try:
                        announced = json.loads(room_file.read_text(encoding='utf-8'))
                        body['room_id'], body['room_round'] = announced['room_id'], active_round
                        body['delay'] = announced['delay']
                    except (OSError, ValueError, KeyError):
                        pass
                try:
                    snapshot = sync(url, ticket, dict(body))
                    if snapshot.get('transport') != transport:
                        raise HillError('Actualiza Django y los dos launchers: la pareja debe usar el mismo transporte de KOTH.')
                    registered = True
                    last_success = time.monotonic()
                except OSError as error:
                    if time.monotonic() - last_success >= 12:
                        raise HillError('Se perdió la conexión con Django. Se detuvo el combate; vuelve a conectar.') from None
                    print(str(error), flush=True)
                else:
                    if isinstance(snapshot.get('event'), dict):
                        board = json.dumps({key: snapshot.get(key) for key in ('event', 'role', 'ready', 'reason')},
                                           ensure_ascii=True, sort_keys=True)
                        if board != last_board:
                            print('KOTH_STATE ' + board, flush=True)
                            last_board = board
                    round_id = snapshot['round_id']
                    if blocked_round is not None and round_id != blocked_round:
                        blocked_round = None
                        # Publish availability for the new pair before starting it.
                        continue
                    if watch_failed_round is not None and round_id != watch_failed_round:
                        watch_failed_round = None
                    if process is not None and (round_id != active_round or snapshot['role'] != active_role or not snapshot['ready']):
                        stop_match(process, child_stop)
                        process = None
                        if round_id == active_round and active_role != 'spectator':
                            blocked_round = active_round
                    if snapshot['status'] == 'finished':
                        print('El torneo finalizó.', flush=True)
                        return 0
                    room_ready = transport == 'zerotier' or snapshot['role'] == 'host' or bool((snapshot.get('host') or {}).get('relay_room'))
                    reason = snapshot['reason']
                    if snapshot['ready'] and not room_ready:
                        reason = 'Esperando que el host abra la sala en el servidor principal.'
                    message = (' | '.join(f"{i+1}. {p['name']} ({p['points']} pts)" for i, p in enumerate(snapshot['queue'])),
                               snapshot['role'], reason)
                    if message != last_message:
                        print('Cola: ' + message[0], flush=True)
                        print(f"Turno: {snapshot['role'] or 'en espera'}. {reason}", flush=True)
                        last_message = message
                    watching_failed = snapshot['role'] == 'spectator' and watch_failed_round == round_id
                    watching_disabled = snapshot['role'] == 'spectator' and getattr(args, 'no_spectators', False)
                    if process is None and blocked_round is None and snapshot['ready'] and not watching_failed and not watching_disabled and room_ready:
                        child_stop.unlink(missing_ok=True)
                        room_file.unlink(missing_ok=True)
                        active_round = round_id
                        active_role = snapshot['role']
                        print('Iniciando modo espectador.' if active_role == 'spectator' else f"Iniciando combate como {active_role}.", flush=True)
                        child_env = os.environ.copy()
                        child_env.pop('UN5_HILL_TICKET', None)
                        if active_role == 'spectator':
                            child_env.pop('UN5_NETPLAY_SESSION', None)
                        if snapshot.get('spectator_key'):
                            child_env['UN5_SPECTATOR_KEY'] = snapshot['spectator_key']
                        else:
                            child_env.pop('UN5_SPECTATOR_KEY', None)
                        process = subprocess.Popen(match_command(args, snapshot, child_stop, room_file), env=child_env)
                # Remain responsive to STOP while waiting between heartbeats.
                for _ in range(20):
                    if args.stop_file and Path(args.stop_file).exists():
                        break
                    time.sleep(0.1)
        finally:
            stop_match(process, child_stop)
            try:
                release_game(args)
            except Exception as error:
                print(f'No se pudo liberar PCSX2 al salir de KOTH: {error}', flush=True)
            try:
                if registered:
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
