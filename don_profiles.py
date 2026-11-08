"""Validate a frozen D.O.N state and make a portable 2/3/4-player manifest."""
import argparse
import hashlib
import json
import os
import struct
import zipfile
from pathlib import Path

from build_don import SHARED_SIZE
from game_adapters import get_game, validate_metadata


PORTABLE_FIELDS = ('schema', 'adapter', 'experimental', 'online_verified', 'hash_kind',
                   'source_serial', 'source_crc', 'source_elf_sha256', 'boot_crc', 'boot_sha256',
                   'payload_base', 'reserve_size', 'shared_base', 'shared_size',
                   'code_size', 'code_sha256', 'symbols')


def validate_state(state, metadata, players):
    state = Path(state)
    with zipfile.ZipFile(state) as archive:
        if archive.getinfo('eeMemory.bin').file_size != 32*1024*1024:
            raise ValueError('El estado no contiene la RAM de EE completa.')
        memory = archive.read('eeMemory.bin')
    game = validate_metadata(metadata)
    BASE = game.base
    base = metadata['shared_base']
    if not BASE <= base <= BASE+metadata['reserve_size']-SHARED_SIZE:
        raise ValueError('El bloque compartido está fuera de la reserva.')
    header = struct.unpack_from('<16I', memory, base)
    compatible_counts = (players, 4) if game.slug == 'digimon' else (players,)
    if (header[:3] != (game.magic, 1, SHARED_SIZE) or header[3:6] != (1, 0, 1)
            or header[8] != 0 or header[9] != 1 or header[13] not in compatible_counts):
        raise ValueError('El estado no está congelado en frame 0 para esta cantidad de jugadores.')
    size = metadata['code_size']
    if not 0 < size <= base-BASE or hashlib.sha256(memory[BASE:BASE+size]).hexdigest() != metadata['code_sha256']:
        raise ValueError('El estado contiene otra compilación del hook.')
    if game.slug == 'digimon':
        from build_digimon import ARENA_REFERENCES
        for high, _, new_high, low, _, new_low in ARENA_REFERENCES:
            if (struct.unpack_from('<I', memory, high)[0] != new_high or
                    struct.unpack_from('<I', memory, low)[0] != new_low):
                raise ValueError('El estado Digimon no reserva la memoria del adaptador en el asignador del juego.')


def create_profile(state, metadata, players, emulator, destination):
    if players not in (2, 3, 4) or not emulator or len(emulator) > 100:
        raise ValueError('Se requieren 2–4 jugadores y la versión exacta de PCSX2.')
    state, destination = Path(state), Path(destination)
    validate_state(state, metadata, players)
    game = validate_metadata(metadata)
    portable = {key: metadata[key] for key in PORTABLE_FIELDS}
    if game.slug == 'digimon':
        portable['arena_reservation'] = metadata['arena_reservation']
        portable['pad_layout'] = metadata['pad_layout']
    symbols_data = (json.dumps(portable, sort_keys=True, indent=2)+'\n').encode()
    manifest = {'game': game.game, 'crc': metadata['boot_crc'], 'disc_sha256': metadata['disc_sha256'],
                'state_sha256': hashlib.sha256(state.read_bytes()).hexdigest(),
                'symbols_sha256': hashlib.sha256(symbols_data).hexdigest(),
                'adapter': metadata['adapter'], 'emulator': emulator,
                'pads': game.pads(players)}
    destination.mkdir(parents=True, exist_ok=True)
    # Never silently replace the initial state/manifest for an existing profile.
    if any((destination/name).exists() for name in ('manifest.json', 'symbols.json', 'profile.json')):
        raise ValueError('El perfil de destino ya existe; usa otra carpeta para esta revisión.')
    (destination/'symbols.json').write_bytes(symbols_data)
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    profile = {'players': players, 'screen': game.screen, 'state': str(state.resolve()),
               'manifest': str((destination/'manifest.json').resolve()),
               'symbols': str((destination/'symbols.json').resolve()), 'online_verified': False}
    (destination/'profile.json').write_text(json.dumps(profile, indent=2)+'\n')
    return profile


def select_profile(root, players, expected_adapter=None):
    """Choose the newest revision for the requested count and validate its files.

    An invalid latest revision is reported; it never silently selects an older
    arrangement of players. Complete local profiles, not server-supplied paths,
    are the input to this function.
    """
    if players not in (2, 3, 4):
        raise ValueError('Selecciona 2, 3 o 4 jugadores.')
    files = sorted((Path(root)/f'{players}p').glob('*/profile.json'),
                   key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not files:
        raise ValueError(f'Falta capturar un estado de {players} jugadores.')
    folder = files[0].parent
    profile = json.loads(files[0].read_text())
    manifest = json.loads((folder/'manifest.json').read_text())
    symbols_path = folder/'symbols.json'
    symbols_data = symbols_path.read_bytes()
    symbols = json.loads(symbols_data)
    game = get_game(manifest['game'])
    local_state = folder/game.state_name
    state = local_state if local_state.is_file() else Path(profile['state'])
    if (profile['players'] != players or manifest['adapter'] != game.adapter or
            manifest['pads'] != game.pads(players) or
            manifest['adapter'] != symbols['adapter'] or manifest['crc'] != symbols['boot_crc']):
        raise ValueError('El perfil no corresponde a esta cantidad de jugadores y adaptador.')
    if (hashlib.sha256(state.read_bytes()).hexdigest() != manifest['state_sha256'] or
            hashlib.sha256(symbols_data).hexdigest() != manifest['symbols_sha256']):
        raise ValueError('Los archivos del perfil cambiaron desde su captura.')
    if expected_adapter:
        if manifest['disc_sha256'] != expected_adapter['disc_sha256']:
            raise ValueError('El perfil corresponde a otra ISO.')
        for key in ('adapter', 'boot_sha256', 'shared_base', 'code_sha256'):
            if symbols[key] != expected_adapter[key]:
                raise ValueError('El perfil corresponde a otra compilación del adaptador.')
    validate_state(state, symbols, players)
    return {'players': players, 'state': str(state.resolve()),
            'manifest': str((folder/'manifest.json').resolve()),
            'symbols': str(symbols_path.resolve()), 'screen': profile['screen'],
            'online_verified': False}


def index_profiles(root, expected_adapter=None):
    root = Path(root)
    entries = {}
    for count in (2, 3, 4):
        entries[str(count)] = select_profile(root, count, expected_adapter)
    games = {json.loads(Path(p['manifest']).read_text())['game'] for p in entries.values()}
    if len(games) != 1:
        raise ValueError('El catálogo mezcla perfiles de juegos distintos.')
    result = {'schema': 1, 'game': games.pop(), 'profiles': entries, 'online_verified': False}
    temporary = root/'catalog.json.tmp'
    temporary.write_text(json.dumps(result, indent=2)+'\n')
    os.replace(temporary, root/'catalog.json')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--index', type=Path, help='Verificar y registrar los tres perfiles de esta carpeta')
    parser.add_argument('--adapter', type=Path, default=Path('build/don/adapter.json'))
    parser.add_argument('--players', type=int, choices=(2, 3, 4))
    parser.add_argument('--emulator')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        metadata = json.loads(args.adapter.read_text())
        if args.index:
            result = index_profiles(args.index, metadata)
        else:
            if not all((args.state, args.players, args.emulator, args.output)):
                parser.error('Para capturar un perfil se requieren --state, --players, --emulator y --output.')
            result = create_profile(args.state, metadata, args.players, args.emulator, args.output)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as error:
        parser.exit(1, str(error)+'\n')
