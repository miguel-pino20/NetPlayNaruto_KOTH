"""D.O.N SLPS-25675 profile and read-only diagnostics for the original boot ELF.

This module cannot start netplay or inject code. The experimental hook and its
PINE driver live in don_hook/ and don_core.py; simulation hashes remain unverified.
"""
import argparse
import hashlib
import json
import struct

from disc_image import inspect_disc
from pine import Pine, PineError, same_serial


SERIAL = 'SLPS-25675'
CRC = '82EA02B7'
ELF_SHA256 = '994e840123eb5a4cd5d13170a52fdca275dabb0a9f4585665b5d0fc67f9180c1'
# Hashes verified from the user's boot ELF, not just inferred from a game title.
CODE_RANGES = {
    'scePadRead': (0x118E38, 0x78, '7314099f4b42e95dd691f542653fe78fe5a4ee30b9a8ce8c4ed63e815a348d97'),
    'pad_poll': (0x138FB0, 0x3E0, 'c05977fe6825a8c3015b77702c1adca3c762a6c2afe35323e7361d95ba28dbce'),
    'mtap_query': (0x255EA0, 0xE0, 'a51e8085f23bc316a9690cca0888eabcdaf17dbe2454d7cde0eef6959a957166'),
}
# Public UI is 1-based. libpad's arguments in the executable are 0-based.
MULTITAP_PADS = tuple((1, slot) for slot in range(1, 5))
MULTITAP_MODE = 0x4D69E8
PAD_COUNT = 0x4D69F8
PAD_INITIALIZED = 0x4D6A00
# Pending vertical blanks; the game resets this at 0x138B30 after polling pads.
# It is not a monotonic simulation-frame counter and must not drive lockstep.
VBLANK_PENDING = 0x4D6A08
PAD_RECORDS, PAD_STRIDE = 0x4D6A80, 0x4C


def inspect_iso(path):
    report, elf = inspect_disc(path)
    matched = report['serial'] == SERIAL and report['pcsx2_crc'] == CRC and report['elf_sha256'] == ELF_SHA256
    report.update({'game': 'don' if matched else None, 'profile_matches': matched,
                   'netplay_available': False, 'transport': 'zerotier',
                   'reason': ('El online de D.O.N todavía requiere validar el estado de la simulación.' if matched
                              else 'La imagen no coincide con el ejecutable de D.O.N verificado.'),
                   'multitap_pads': [{'port': port, 'slot': slot} for port, slot in MULTITAP_PADS] if matched else []})
    if matched:
        report['code_verified'] = {
            name: hashlib.sha256(elf.read_virtual(address, size)).hexdigest() == expected
            for name, (address, size, expected) in CODE_RANGES.items()}
    return report


def read_bytes(pine, address, size):
    result = bytearray()
    for first in range(0, size, 800):
        count = min(size-first, 800)
        widths = [min(8, count-offset) for offset in range(0, count, 8)]
        # All diagnostic ranges are multiples of 8, except pad records (76 bytes).
        ops = []
        offset = 0
        for width in widths:
            while width:
                word = next(n for n in (8, 4, 2, 1) if n <= width)
                ops.append(('r', address+first+offset, word))
                width -= word
                offset += word
        for value, op in zip(pine.batch(ops), ops):
            result.extend(value.to_bytes(op[2], 'little'))
    return bytes(result)


def probe(pine):
    """Read identity/code first, then inspect four records; never issue a write."""
    if not same_serial(pine.game_id(), SERIAL) or pine.game_crc() != CRC:
        raise ValueError('Abre D.O.N Japan SLPS-25675, CRC 82EA02B7, antes del diagnóstico.')
    for name, (address, size, expected) in CODE_RANGES.items():
        if hashlib.sha256(read_bytes(pine, address, size)).hexdigest() != expected:
            raise ValueError(f'El código de {name} no coincide con el perfil de D.O.N; no se leen sus estructuras.')
    before = pine.read(VBLANK_PENDING)
    mode, count, initialized = pine.batch([('r', a, 4) for a in (MULTITAP_MODE, PAD_COUNT, PAD_INITIALIZED)])
    data = read_bytes(pine, PAD_RECORDS, PAD_STRIDE*4)
    players = []
    multitap = mode == 1 and count == 4
    pads = MULTITAP_PADS if multitap else ((1, 1), (2, 1)) if mode == 0 and count == 2 else ()
    for slot, (port, pad_slot) in enumerate(pads):
        record = data[slot*PAD_STRIDE:(slot+1)*PAD_STRIDE]
        players.append({'player': slot+1, 'port': port, 'slot': pad_slot,
                        'init_state': struct.unpack_from('<h', record, 0)[0],
                        'pad_state': struct.unpack_from('<h', record, 4)[0],
                        'held': f"{struct.unpack_from('<I', record, 12)[0]:08X}",
                        'pressed': f"{struct.unpack_from('<I', record, 16)[0]:08X}",
                        'released': f"{struct.unpack_from('<I', record, 20)[0]:08X}"})
    after = pine.read(VBLANK_PENDING)
    return {'game': 'don', 'serial': SERIAL, 'pcsx2_crc': CRC, 'read_only': True,
            'netplay_available': False, 'initialized': bool(initialized),
            'multitap_mode': mode, 'pad_count': count, 'four_pad_mode': multitap,
            'players': players,
            'vblank_pending_before': before, 'vblank_pending_after': after,
            'sample_atomic': False,
            'note': 'Lectura no atómica; no acredita una partida sincronizada.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Diagnóstico D.O.N de solo lectura; no habilita netplay.')
    sub = parser.add_subparsers(dest='command', required=True)
    iso = sub.add_parser('inspect-iso')
    iso.add_argument('path')
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
