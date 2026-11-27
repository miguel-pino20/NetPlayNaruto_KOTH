"""Mobile adapter: reuse desktop protocols without starting a match prematurely."""
from __future__ import annotations

import ipaddress
import json
import os
import queue
import re
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit


if __package__:
    from .mobile_locale import tr
else:
    from mobile_locale import tr


def configure_storage(directory):
    # Must run before importing appdata/discord_auth/koth_client.
    os.environ['XDG_CONFIG_HOME'] = str(Path(directory).resolve())


def https_url(value):
    from koth_client import site_url
    value = site_url(value.strip())
    if urlsplit(value).scheme != 'https':
        raise ValueError(tr('Usa una URL HTTPS para proteger tu sesión.'))
    return value


def validate_address(value):
    address = ipaddress.IPv4Address(value.strip())
    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local or address.is_reserved:
        raise ValueError(tr('Introduce la IPv4 asignada por ZeroTier.'))
    return str(address)


def zerotier_prefix(local_address):
    return validate_address(local_address).rsplit('.', 1)[0] + '.' if local_address.strip() else ''


def resolve_zerotier_host(value, local_address=''):
    value = value.strip()
    if value.isascii() and value.isdecimal() and len(value) <= 3:
        value = zerotier_prefix(local_address) + str(int(value))
    return validate_address(value)


def discover_zerotier_rooms(local_address, session=None):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic, sleep
    from rooms import RoomListener, ZEROTIER_GAME_PORT, django_rooms, uses_interface
    from koth_client import DEFAULT_URL

    listener = RoomListener(zerotier_address=local_address)
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            remote = worker.submit(django_rooms, DEFAULT_URL, session, local_address, ZEROTIER_GAME_PORT)
            if not listener.error:
                # The shared PC and Android hosts announce once every two seconds.
                deadline = monotonic() + 2.5
                while monotonic() < deadline:
                    listener.poll()
                    sleep(.15)
            rooms = {(room['ip'], room['port']): room for room in remote.result()}
        if listener.error and not rooms:
            raise OSError(listener.error)
        rooms.update(((room['ip'], room['port']), room) for room in listener.poll())
        return [room for room in rooms.values()
                if room['status'] == 'waiting' and room.get('game') in ('un5', 'un6')
                and room['port'] == ZEROTIER_GAME_PORT and room['ip'] != local_address
                and uses_interface(room['ip'], local_address)]
    finally:
        listener.close()


def active_events(events, *, casual):
    return [event for event in events
            if event.get('status') in ('draft', 'running') and bool(event.get('casual')) == casual]


def event_match(details, fallback_game=None, *, event=None):
    from koth_client import KOTH_STATES

    event = event or {}
    state = details.get('match_state') or event.get('match_state')
    if state:
        if state not in KOTH_STATES:
            raise ValueError(tr('El estado configurado no es compatible.'))
        return KOTH_STATES[state]
    for source in (details, event):
        game = source.get('match_game') or source.get('game')
        if game in ('un5', 'un6'):
            return game, None
    # Older events may not advertise a game or a state.
    return (fallback_game, None) if fallback_game in ('un5', 'un6') else None


STORE_CATEGORIES = {'background': 'backgrounds', 'character': 'characters'}


def appearance_store(session, preference, *, item=None):
    from discord_auth import api_call
    from koth_client import DEFAULT_URL

    headers = {'X-Netplay-Session': session}
    path = f'/api/netplay/store/{STORE_CATEGORIES[preference]}/'
    if item is not None:
        return api_call(DEFAULT_URL, 'POST', f"{path}{item['id']}/purchase/", {'price': item['price']},
                        extra_headers=headers, follow_redirects=False)
    response = api_call(DEFAULT_URL, 'GET', path, extra_headers=headers, follow_redirects=False)
    response['items'] = [
        entry for entry in response['items']
        if type(entry.get('id')) is int and entry['id'] > 0 and type(entry.get('owned')) is bool
        and type(entry.get('price')) is int and entry['price'] >= 0
        and isinstance(entry.get('name'), str) and entry['name'].strip()
        and re.fullmatch(r'[0-9a-f]{64}', str(entry.get('image_version', '')))
    ]
    return response


def owned_appearance(session):
    return {preference: {str(item['id']): item for item in appearance_store(session, preference)['items'] if item['owned']}
            for preference in STORE_CATEGORIES}


def appearance_cache_path(directory, owner, preference, item):
    account_key = sha256(str(owner).encode()).hexdigest()
    category = STORE_CATEGORIES[preference]
    extension = 'png' if preference == 'character' else 'jpg'
    return Path(directory) / 'appearance' / account_key / category / f"{item['id']}-{item['image_version']}.{extension}"


def cache_appearance(directory, owner, preference, item, session):
    from urllib.request import HTTPSHandler, Request, build_opener
    from discord_auth import NoRedirect, UA, ssl_context
    from koth_client import DEFAULT_URL

    path = appearance_cache_path(directory, owner, preference, item)
    if path.is_file():
        return path
    # Django supplies bounded JPEG backgrounds and transparent PNG sprites for mobile rendering.
    maximum = 1024 * 1024
    category = STORE_CATEGORIES[preference]
    url = f"{DEFAULT_URL}/api/netplay/store/{category}/{item['id']}/preview/"
    request = Request(url, headers={'User-Agent': UA, 'X-Netplay-Session': session})
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl_context()))
    with opener.open(request, timeout=12) as response:
        data = response.read(maximum + 1)
    signature = b'\x89PNG\r\n\x1a\n' if preference == 'character' else b'\xff\xd8\xff'
    if len(data) > maximum or not data.startswith(signature):
        raise ValueError(tr('La tienda devolvió una imagen inválida.'))
    return _cache_image(path, data)


def _cache_image(path, data):
    from tempfile import NamedTemporaryFile

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def history_portraits(directory, fights):
    from concurrent.futures import ThreadPoolExecutor

    sources = {player.get('portrait') for fight in fights for player in fight['players']}
    paths = sorted(path for path in sources if isinstance(path, str)
                   and re.fullmatch(r'/static/characters/[0-9]+(?:\.[a-f0-9]+)?\.png', path))
    if not paths:
        return {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        images = pool.map(lambda path: _history_portrait(directory, path), paths)
        return {path: image for path, image in zip(paths, images) if image is not None}


def _history_portrait(directory, source):
    from urllib.request import HTTPSHandler, build_opener
    from discord_auth import NoRedirect, ssl_context
    from koth_client import DEFAULT_URL

    maximum = 512 * 1024
    path = Path(directory) / 'history-portraits' / source.rsplit('/', 1)[-1]
    if path.is_file():
        return path
    try:
        opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl_context()))
        with opener.open(DEFAULT_URL + source, timeout=4) as response:
            data = response.read(maximum + 1)
        if not 24 <= len(data) <= maximum or not data.startswith(b'\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR'):
            return None
        dimensions = (int.from_bytes(data[offset:offset+4], 'big') for offset in (16, 20))
        if not all(0 < size <= 1024 for size in dimensions):
            return None
        return _cache_image(path, data)
    except (OSError, ValueError):
        return None


def pine_diagnostics(slot, android=True):
    from pine import Pine
    slot = int(slot)
    if not 1 <= slot <= 65535:
        raise ValueError(tr('El puerto PINE debe estar entre 1 y 65535.'))
    client = Pine(slot=slot, timeout=3, transport='tcp' if android else None)
    try:
        client.connect()
        status = client.status()
        if status == 2:
            return tr('PINE responde. Abre Naruto en el emulador para identificar el juego.')
        status_label = {0: 'en ejecución', 1: 'pausado'}.get(status, str(status))
        return '\n'.join((tr('PINE conectado: {endpoint}', endpoint=client.endpoint),
                          tr('Estado: {status}', status=tr(status_label)),
                          tr('Juego: {game}', game=client.game_id()), f'CRC: {client.game_crc()}',
                          tr('Emulador: {version}', version=client.version()),
                          tr('Diagnóstico de solo lectura. No valida todavía NetPad ni la sincronía.')))
    finally:
        client.close()


def load_preferences(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def make_account(server):
    from discord_auth import DiscordMixin

    class MobileAccount(DiscordMixin):
        def __init__(self):
            self.q = queue.Queue()
            self._init_account(https_url(server))

        def _load_avatar(self):
            # This minimal interface displays names only; avoid downloading PNGs.
            self.avatar_png = None

    return MobileAccount()
