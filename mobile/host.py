"""Android host orchestration; all gameplay and wire logic stays in netplay.py."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen

if __package__:
    from .backend import validate_address
    from .mobile_locale import tr
else:
    from backend import validate_address
    from mobile_locale import tr

SERVER = 'https://un5netplay.duckdns.org'
GAMES = {'un5': 'C071D4C1', 'un6': '688C83D6'}
ACTIVE = {'starting', 'preparing', 'waiting', 'playing', 'stopping'}


def file_tag(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def paths(directory, game):
    if game not in GAMES:
        raise ValueError(tr('Selecciona UN5 o UN6.'))
    root = Path(directory) / 'host' / game
    return root / 'match.p2s', root / 'symbols.json'


def prepare_files(directory, game):
    from discord_auth import api_call, ssl_context
    state, symbols = paths(directory, game)
    query = '?game=un6' if game == 'un6' else ''
    info = api_call(SERVER, 'GET', '/default' + query)
    for kind, destination in (('state', state), ('symbols', symbols)):
        expected = info.get(kind, '')
        if len(expected) != 16 or any(c not in '0123456789abcdef' for c in expected):
            raise ValueError(tr('El servidor no publicó un identificador válido para {kind}', kind=kind))
        if destination.exists() and file_tag(destination) == expected:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix('.part')
        try:
            digest, total = hashlib.sha256(), 0
            request = Request(SERVER + '/default/' + kind + query, headers={'User-Agent': 'UN5Mobile/0.2'})
            with urlopen(request, timeout=30, context=ssl_context()) as response, temp.open('wb') as output:
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > (128 * 1024 * 1024 if kind == 'state' else 1024 * 1024):
                        raise ValueError(tr('El archivo excede el tamaño esperado.'))
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest()[:16] != expected:
                raise ValueError(tr('La descarga no coincide con el archivo publicado: {kind}', kind=kind))
            if kind == 'symbols':
                table = json.loads(temp.read_text())
                if not isinstance(table, dict) or not {'g_np', 'g_np_report'} <= table.keys():
                    raise ValueError(tr('Los símbolos no contienen NetPad.'))
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
    return state, symbols


def session_arguments(config):
    from netlink import DEFAULT_SERVER, DEFAULT_API_URL
    state, symbols = paths(config['directory'], config['game'])
    transport = config.get('transport', 'direct')
    if transport not in ('direct', 'server'):
        raise ValueError(tr('Modo de conexión desconocido.'))
    role = config.get('role', 'host')
    if role not in ('host', 'guest'):
        raise ValueError(tr('Rol desconocido.'))
    slot = int(config['pine_slot'])
    if not 1 <= slot <= 65535:
        raise ValueError(tr('Puerto PINE inválido.'))
    args = ['--symbols', str(symbols), '--pine-slot', str(slot), '--stop-file', config['stop_file'],
            role, '--state', str(state), '--delay', '3',
            '--nick', config.get('nick', 'Player1')]
    args += ['--port', '47400', '--no-announce'] if role == 'host' else ['--bind-port', '0']
    if transport == 'server':
        args += ['--server', DEFAULT_SERVER, '--api-url', DEFAULT_API_URL, '--relay-only']
        if role == 'host':
            return args + ['--room-file', str(Path(config['directory']) / 'host-room.json')]
        room = str(config.get('room_id', '')).strip()
        if not room or len(room) > 64 or not all(c.isalnum() or c in '-_' for c in room):
            raise ValueError(tr('Selecciona una sala válida del servidor.'))
        return args + ['--room', room, '--fetch-state']
    bind = validate_address(config['address']) if config.get('address') else '0.0.0.0'
    args += ['--zerotier', '--bind-address', bind, '--server', '']
    if role == 'guest':
        args += ['--connect', validate_address(config.get('host_ip', '')) + ':47400']
    return args


def host_arguments(config):
    return session_arguments(dict(config, role='host'))


def client_arguments(config):
    return session_arguments(dict(config, role='guest'))


def ensure_controllers(client):
    """Both virtual ports must exist; local input remains on pad 1 on either peer."""
    changed = []
    for section in ('Pad1', 'Pad2'):
        value = client.armsx2_get_setting(section, 'Type')
        if value in ('', 'None', 'NotConnected'):
            client.armsx2_set_setting(section, 'Type', 'DualShock2')
            changed.append(section)
        elif value != 'DualShock2':
            raise ValueError(tr('{section}: selecciona DualShock 2 en ARMSX2 (actual: {value}).', section=section, value=value))
    return changed


def wait_for_match(config, report):
    from core_link import PineCore, resolve_base
    from pine import Pine, PineError
    _, symbols = paths(config['directory'], config['game'])
    deadline = time.monotonic() + 90
    loaded, configured, last, last_report = False, False, '', 0.0
    while time.monotonic() < deadline and not Path(config['stop_file']).exists():
        client = Pine(int(config['pine_slot']), timeout=2, transport='tcp')
        try:
            client.connect()
            status = client.status()
            if status == 2:
                raise ValueError(tr('Abre Naruto en ARMSX2.'))
            if client.game_crc() != GAMES[config['game']]:
                raise ValueError(tr('El juego abierto no coincide con el seleccionado.'))
            if not configured:
                ensure_controllers(client)
                configured = True
            if not loaded:
                # PINE index 0 is slot 1 in the ARMSX2 UI. File installation is not supported by PINE.
                client.load_state(0)
                loaded = True
                time.sleep(1.5)
            base, _, _ = resolve_base(client, symbols)
            if not PineCore(base, pine=client, serial=None).frozen():
                raise ValueError(tr('Falta el estado compartido preparado en el slot 1 de ARMSX2.'))
            return
        except (PineError, OSError, RuntimeError, ValueError, KeyError) as error:
            last = str(error)
            if time.monotonic() - last_report >= 3:
                report('preparing', tr('Vuelve a ARMSX2 y pulsa Reanudar.') + ' ' + last)
                last_report = time.monotonic()
        finally:
            client.close()
        time.sleep(0.5)
    if Path(config['stop_file']).exists():
        raise InterruptedError(tr('Creación cancelada.'))
    raise RuntimeError(tr('No se pudo preparar NetPad en 90 s. {detail}', detail=last))


def run_host(config, report):
    """Runs in its own Android service process; never in the Kivy activity."""
    import netplay
    argv = session_arguments(config)
    state, symbols = paths(config['directory'], config['game'])
    if not state.is_file() or not symbols.is_file():
        raise ValueError(tr('Prepara primero los archivos compartidos.'))
    if config.get('transport') == 'server':
        from appdata import load_session, clear_session
        from discord_auth import api_call, AccountError, account_game_nick
        token, account = load_session()
        if token:
            try:
                account = api_call(SERVER, 'GET', '/accounts/me', token=token)
            except AccountError as error:
                if error.code == 401:
                    clear_session()
                raise RuntimeError(tr('No se pudo verificar Discord. Revisa la sesión en la pestaña Discord.')) from None
            os.environ['UN5_NETPLAY_SESSION'] = token
            config = dict(config, nick=account_game_nick(account) or config.get('nick', 'Android P1'))
            argv = session_arguments(config)
        else:
            os.environ.pop('UN5_NETPLAY_SESSION', None)
            if config.get('role') == 'guest':
                raise ValueError(tr('Inicia sesión con Discord para entrar al servidor principal.'))
        if config.get('role') == 'guest':
            from netlink import Api, DEFAULT_API_URL
            room = Api(DEFAULT_API_URL).get_room(config['room_id'])
            if room.get('tag') != file_tag(state):
                raise ValueError(tr('La sala no usa el estado del juego seleccionado.'))
    else:
        from appdata import load_session
        token, _ = load_session()
        if token:
            os.environ['UN5_SCOREBOARD_SESSION'] = token
        else:
            os.environ.pop('UN5_SCOREBOARD_SESSION', None)
    wait_for_match(config, report)
    # Android detection is built into Pine. No subprocess executable is required.
    report('preparing', tr('Estado, mandos y hook comprobados. Conectando…'))
    try:
        return netplay.main(argv)
    finally:
        # The UI can freeze ARMSX2 while stopping. Retry release after the user
        # returns, rather than leaving the game's NetPad barrier armed forever.
        from core_link import PineCore, resolve_base
        from pine import Pine, PineError
        report('stopping', tr('Liberando controles. Mantén ARMSX2 visible…'))
        deadline = time.monotonic() + 30
        released = False
        while time.monotonic() < deadline:
            client = Pine(int(config['pine_slot']), timeout=2, transport='tcp')
            try:
                client.connect()
                if client.game_crc() != GAMES[config['game']]:
                    break
                base, _, _ = resolve_base(client, symbols)
                core = PineCore(base, pine=client, serial=None)
                core.put('hold', 0)
                core.stop()
                released = True
                break
            except (PineError, OSError, RuntimeError, ValueError):
                pass
            finally:
                client.close()
            time.sleep(0.5)
        if not released:
            raise RuntimeError(tr('No se pudieron liberar los controles. Abre ARMSX2 y recarga un estado o reinicia el juego.'))
