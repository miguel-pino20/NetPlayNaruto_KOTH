"""Read-only analysis of Digimon Rumble Arena 2 USA SLUS-21067.

Addresses below were located by static inspection of this exact executable.
Their role and the mapping from the eight objects to players still need live
verification. This module installs no hook and cannot start a netplay session.
"""
import argparse
import hashlib
import json
from pathlib import Path

from disc_image import inspect_disc
from don_adapter import read_bytes
from pine import Pine, PineError, same_serial

GAME = 'digimon-rumble-arena-2'
SERIAL = 'SLUS-21067'
CRC = '568A5C78'
ELF_SHA256 = '590f453c7e39faeec8a2e46352b2655a18d1eb6e12fe693fe75583efcd15dacd'
# Names express statically inferred roles, not dynamically verified hook sites.
CODE_RANGES = {
    'pad_read': (0x3F2F18, 0x164, '1108125dae21751aeb0f7fe6d6aaf98a4e2f5db6b3c9bb7dbc3185c1078a05f0'),
    'pad_get_state': (0x3F3080, 0x80, '26f6cffa90c2b450f33644dc5fb83ede80e63858d19cbbf0262d2de48b7742df'),
    'pad_decode': (0x3ED650, 0x568, '563252a1b4992453bb47d31cc13288bba4e955d707b03de0cfbf7c364ca6744b'),
    'pad_update_all': (0x3EDFD0, 0xA0, 'c8397cdee18c9af6d6b13ba6f5576cd08b5d394eb0d975525e70794137eeaf10'),
}
PAD_OBJECTS, PAD_STRIDE, PAD_OBJECT_COUNT = 0x565E00, 0x240, 8
FIELDS = {'port_raw': 0xD0, 'slot_raw': 0xD4, 'state_raw': 0x200,
          'enabled_raw': 0xC0, 'pad_state_raw': 0xCC}


def inspect_iso(path):
    report, elf = inspect_disc(path)
    matched = (report['serial'] == SERIAL and report['pcsx2_crc'] == CRC
               and report['elf_sha256'] == ELF_SHA256)
    report.update(game=GAME if matched else None, profile_matches=matched,
                  read_only=True, netplay_available=False, transport='zerotier',
                  player_mapping_verified=False,
                  reason='Análisis estático; faltan el adaptador de entradas y la validación de sincronía.')
    if matched:
        report['code_verified'] = {
            name: hashlib.sha256(elf.read_virtual(address, size)).hexdigest() == expected
            for name, (address, size, expected) in CODE_RANGES.items()}
        report['pad_objects'] = {'address': PAD_OBJECTS, 'stride': PAD_STRIDE, 'count': PAD_OBJECT_COUNT}
    return report


def probe(pine):
    """Verify the expected game/code before reading statically located objects.

    No calls to the game's functions and no writes are made. Object indices are
    deliberately not labelled P1..P4: a live mapping has not been established.
    """
    if not same_serial(pine.game_id(), SERIAL) or pine.game_crc() != CRC:
        raise ValueError('Abre Digimon Rumble Arena 2 USA, SLUS-21067 / 568A5C78.')
    for name, (address, size, expected) in CODE_RANGES.items():
        if hashlib.sha256(read_bytes(pine, address, size)).hexdigest() != expected:
            raise ValueError(f'El código de {name} difiere; no se leen las estructuras de mandos.')
    objects = []
    for index in range(PAD_OBJECT_COUNT):
        address = PAD_OBJECTS+index*PAD_STRIDE
        values = pine.batch([('r', address+offset, 4) for offset in FIELDS.values()])
        fields = dict(zip(FIELDS, values))
        fields['port_slot_in_range'] = fields['port_raw'] in (0, 1) and fields['slot_raw'] in range(4)
        fields['connector'] = (f"{fields['port_raw']+1}{'ABCD'[fields['slot_raw']]}"
                               if fields['port_slot_in_range'] else None)
        # Port/slot fields are zero-based; initialization and mapping to humans
        # must be confirmed separately before interpreting any of these slots.
        objects.append({'object_index': index, 'address': f'{address:08X}', **fields})
    layout_matches = [(p['port_raw'], p['slot_raw']) for p in objects] == [
        (index % 2, index // 2) for index in range(PAD_OBJECT_COUNT)]
    return {'game': GAME, 'serial': SERIAL, 'pcsx2_crc': CRC,
            'emulator': pine.version(), 'emulator_status': pine.status(),
            'read_only': True, 'netplay_available': False, 'player_mapping_verified': False,
            'port_slot_layout_verified': layout_matches,
            'enabled_connectors': [p['connector'] for p in objects if p['enabled_raw'] and p['connector']],
            'sample_atomic': False, 'objects': objects,
            'note': 'Campos sin interpretar; ocho estructuras no equivalen a ocho jugadores activos.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    iso = sub.add_parser('inspect-iso')
    iso.add_argument('path', type=Path)
    live = sub.add_parser('probe')
    live.add_argument('--pine-slot', type=int, default=28011)
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect-iso':
            result = inspect_iso(args.path)
        else:
            pine = Pine(args.pine_slot, timeout=3)
            try:
                pine.connect()
                result = probe(pine)
            finally:
                pine.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, PineError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
