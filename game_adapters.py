"""Explicit game identities and independent experimental adapter layouts."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Game:
    slug: str
    game: str
    title: str
    short: str
    adapter: str
    serial: str
    crc: str
    elf_sha256: str
    base: int
    magic: int
    state_name: str
    screen: str
    capture_hint: str

    def pads(self, players):
        if type(players) is not int or players not in (2, 3, 4):
            raise ValueError('Selecciona 2, 3 o 4 jugadores.')
        layout = ((1, 1), (2, 1), (2, 2), (2, 3)) if self.slug == 'digimon' else (
            (1, 1), (1, 2), (1, 3), (1, 4))
        return [{'port': port, 'slot': slot} for port, slot in layout[:players]]

    @property
    def core(self):
        if self.slug == 'don':
            from don_core import DonCore
            return DonCore
        from digimon_core import DigimonCore
        return DigimonCore


DON = Game('don', 'don', 'Battle Stadium D.O.N', 'D.O.N', 'don-experimental-input-v1',
    'SLPS-25675', '82EA02B7', '994e840123eb5a4cd5d13170a52fdca275dabb0a9f4585665b5d0fc67f9180c1',
    0x5A6800, 0x34504E44, 'DON-organicense.p2s', 'organicense',
    'En «Organícense», deja los puestos elegidos en JUGADOR y el resto fuera o CPU.')
DIGIMON = Game('digimon', 'digimon-rumble-arena-2', 'Digimon Rumble Arena 2', 'Digimon',
    'digimon-experimental-input-v1', 'SLUS-21067', '568A5C78',
    '590f453c7e39faeec8a2e46352b2655a18d1eb6e12fe693fe75583efcd15dacd',
    0x580000, 0x32474D44, 'Digimon-seleccion.p2s', 'character-select',
    'Estado común para salas de 2–4: deja P1 dentro y P2–P4 en JOIN IN, sin elegir personaje.\n'
    'Se usan 1A, 2A, 2B y 2C: Multitap solo en el puerto 2 y 2D desconectado.\n'
    'Cada PC captura su mando físico 1A.')


def get_game(key='don'):
    for game in (DON, DIGIMON):
        if key in (game.slug, game.game, game.adapter):
            return game
    raise ValueError('Juego o adaptador no compatible con este launcher.')


def validate_metadata(metadata):
    game = get_game(metadata['adapter'])
    if game.slug == 'digimon' and metadata.get('arena_reservation') != 2:
        raise ValueError('El adaptador Digimon necesita la reserva corregida de memoria; prepara una revisión nueva.')
    if game.slug == 'digimon' and metadata.get('pad_layout') != 'port2':
        raise ValueError('El adaptador Digimon debe usar 1A, 2A, 2B y 2C; prepara una revisión actualizada.')
    if (metadata.get('schema') != 1 or metadata.get('source_serial') != game.serial or
            metadata.get('source_crc') != game.crc or metadata.get('source_elf_sha256') != game.elf_sha256 or
            metadata.get('payload_base') != game.base or metadata.get('reserve_size') != 0x10000 or
            metadata.get('shared_size') != 0x5440 or
            not game.base <= metadata.get('shared_base', 0) <= game.base+0x10000-0x5440):
        raise ValueError('Los metadatos no coinciden con la versión conocida del juego.')
    return game
