"""Mobile adapter: reuse desktop protocols without starting a match prematurely."""
from __future__ import annotations

import ipaddress
import json
import os
import queue
from pathlib import Path
from urllib.parse import urlsplit


def configure_storage(directory):
    # Must run before importing appdata/discord_auth/koth_client.
    os.environ['XDG_CONFIG_HOME'] = str(Path(directory).resolve())


def https_url(value):
    from koth_client import site_url
    value = site_url(value.strip())
    if urlsplit(value).scheme != 'https':
        raise ValueError('Usa una URL HTTPS para proteger tu sesión.')
    return value


def validate_address(value):
    address = ipaddress.IPv4Address(value.strip())
    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local or address.is_reserved:
        raise ValueError('Introduce la IPv4 asignada por ZeroTier.')
    return str(address)


def pine_diagnostics(slot, android=True):
    from pine import Pine
    slot = int(slot)
    if not 1 <= slot <= 65535:
        raise ValueError('El puerto PINE debe estar entre 1 y 65535.')
    client = Pine(slot=slot, timeout=3, transport='tcp' if android else None)
    try:
        client.connect()
        status = client.status()
        if status == 2:
            return 'PINE responde. Abre Naruto en el emulador para identificar el juego.'
        return '\n'.join((f'PINE conectado: {client.endpoint}',
                          f'Estado: { {0: "en ejecución", 1: "pausado"}.get(status, status)}',
                          f'Juego: {client.game_id()}', f'CRC: {client.game_crc()}',
                          f'Emulador: {client.version()}',
                          'Diagnóstico de solo lectura. No valida todavía NetPad ni la sincronía.'))
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
