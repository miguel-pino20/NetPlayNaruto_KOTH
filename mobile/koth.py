"""Coordinate Android KOTH sessions through Django in the foreground service."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

from discord_auth import AccountError, api_call
from hill import HillError, file_tag, release_game
from netplay import main as play

if __package__:
    from .host import prepare_files, wait_for_match
    from .mobile_locale import tr
else:
    from host import prepare_files, wait_for_match
    from mobile_locale import tr


ROLES = {'host': 'P1', 'guest': 'P2', 'spectator': 'Espectador'}



def sync(url, ticket, body):
    try:
        return api_call(url, 'POST', '/api/netplay/sync/', body, token=ticket, timeout=4)
    except AccountError as error:
        if error.code == 0 or error.code >= 500:
            raise OSError(str(error)) from error
        raise HillError(str(error)) from error


def play_round(config, snapshot, state, symbols, stop):
    role = snapshot['role']
    host = snapshot['host']
    args = [
        '--symbols', str(symbols), '--pine-slot', str(config['pine_slot']),
        '--stop-file', str(stop), '--parent-stop-file', config['stop_file'],
        'watch' if role == 'spectator' else role, '--state', str(state),
        '--session-epoch', snapshot.get('session_epoch') or snapshot['round_id'],
        '--delay', str(host['delay']), '--nick', config['nick'], '--server', '',
    ]
    if role == 'spectator':
        args += ['--preloaded-state', '--connect', f"{host['address']}:{host['spectator_port']}"]
        os.environ['UN5_SPECTATOR_SOURCES'] = json.dumps(snapshot.get('spectator_sources', []))
    else:
        args += ['--bind-address', config['address']]
        if role == 'guest':
            args += ['--bind-port', '0', '--connect', f"{host['address']}:{host['port']}"]
        else:
            args += ['--port', str(host['port']), '--no-share-state', '--no-announce']
            guest = snapshot.get('guest') or {}
            if guest.get('address'):
                args += ['--expect-guest-ip', guest['address']]
        if snapshot.get('spectator_key'):
            args += ['--spectator-port', '47401']
    if snapshot.get('spectator_key'):
        os.environ['UN5_SPECTATOR_KEY'] = snapshot['spectator_key']
    try:
        return play(args)
    finally:
        os.environ.pop('UN5_SPECTATOR_KEY', None)
        os.environ.pop('UN5_SPECTATOR_SOURCES', None)


def run_koth(config, report):
    parent_stop = Path(config['stop_file'])
    report('preparing', tr('KOTH · Descargando los archivos de la partida. Vuelve a ARMSX2.'))
    state, symbols = prepare_files(config['directory'], config['game'])
    body = {'address': config['address'], 'port': 47400, 'game': config['game'], 'delay': 3,
            'state_tag': file_tag(state), 'symbols_tag': file_tag(symbols), 'available': False,
            'transport': 'zerotier', 'spectators_enabled': True}
    url, ticket = config['url'], config['koth_ticket']
    future = None
    active = blocked = None
    retry_after = 0
    registered = prepared = False
    last_sync = time.monotonic()
    with TemporaryDirectory(dir=config['directory'], prefix='koth-') as temp, ThreadPoolExecutor(max_workers=1) as worker:
        round_stop = Path(temp) / 'stop'
        try:
            while not parent_stop.exists():
                if future and future.done():
                    try:
                        future.result()
                    except (Exception, SystemExit) as error:
                        report('waiting', tr('KOTH · La sesión terminó: {error}', error=error))
                    if not round_stop.exists():
                        blocked = active
                        retry_after = time.monotonic() + 5 if active[1] == 'spectator' else float('inf')
                    future = None
                    prepared = False

                if not prepared and future is None and (blocked is None or time.monotonic() >= retry_after):
                    wait_for_match(config, report)
                    prepared = True
                    last_sync = time.monotonic()

                body['available'] = prepared
                try:
                    snapshot = sync(url, ticket, body)
                except OSError:
                    if time.monotonic() - last_sync >= 12:
                        raise HillError(tr('KOTH perdió la conexión con Django.'))
                else:
                    registered = True
                    last_sync = time.monotonic()
                    if snapshot['status'] == 'finished':
                        return 0
                    role = snapshot.get('role')
                    identity = (snapshot.get('round_id'), role,
                                snapshot.get('session_epoch') or snapshot.get('stream_id'))
                    if snapshot.get('transport') != 'zerotier':
                        raise HillError(tr('KOTH móvil requiere que la pareja utilice ZeroTier.'))
                    if blocked and (blocked[:2] != identity[:2] or time.monotonic() >= retry_after):
                        blocked = None
                    ready = snapshot.get('ready') and role in ROLES
                    if future and (not ready or active != identity):
                        round_stop.touch()
                    if future is None and prepared and ready and blocked is None:
                        round_stop.unlink(missing_ok=True)
                        active = identity
                        future = worker.submit(play_round, config, snapshot, state, symbols, round_stop)
                    role_label = tr(ROLES.get(role, 'En espera'))
                    detail = (tr('Esperando el resultado del organizador.') if blocked and role != 'spectator'
                              else tr('Reproduciendo el combate.') if future and role == 'spectator'
                              else tr('Conectando con el rival.') if future
                              else snapshot.get('reason', ''))
                    report('playing' if future else 'waiting', f'KOTH · {config["event_name"]} · {role_label}\n{detail}')

                for _ in range(20):
                    if parent_stop.exists():
                        break
                    time.sleep(0.1)
        finally:
            round_stop.touch()
            if future:
                try:
                    future.result()
                except (Exception, SystemExit):
                    pass
            if registered:
                try:
                    sync(url, ticket, {**body, 'offline': True})
                except (OSError, HillError):
                    pass
            if prepared:
                try:
                    release_game(SimpleNamespace(pine_slot=config['pine_slot'], symbols=str(symbols)))
                except (Exception, SystemExit) as error:
                    print(f'KOTH: no se pudieron liberar los controles: {error}', flush=True)
    return 0
