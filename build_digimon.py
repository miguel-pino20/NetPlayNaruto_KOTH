"""Prepare a local Digimon boot ELF; never changes the ISO or packages the app.

Run by the state administrator before capturing profiles. Guests use the hook
inside the shared state and do not need clang or a custom ELF on their PCs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

from build_don import jump, sha256_file
from digimon_adapter import CRC, ELF_SHA256
from disc_image import inspect_disc, pcsx2_crc
from mips_link import align, link

BASE, RESERVE, SHARED_SIZE, MAGIC = 0x580000, 0x10000, 0x5440, 0x32474D44
ADAPTER = 'digimon-experimental-input-v1'
HOOKS = {'dg_update_entry': (0x3EDFD0, (0x27BDFFE0, 0xFFB10008)),
         'dg_read_entry': (0x3F2F18, (0x27BDFF20, 0x24030070)),
         'dg_state_entry': (0x3F3080, (0x0080302D, 0x24030070))}
# Digimon has its own arena allocator, independent of SetupHeap/sbrk. All
# of these sites materialize the original end-of-image address 0x5752e4.
# The startup BSS-clear reference intentionally remains unchanged.
ARENA_REFERENCES = (
    (0x3EC20C, 0x3C030057, 0x3C030059, 0x3EC210, 0x246352E4, 0x24630000),
    (0x3EEB04, 0x3C020057, 0x3C020059, 0x3EEB0C, 0x245352E4, 0x24530000),
    (0x3EECB0, 0x3C020057, 0x3C020059, 0x3EECB8, 0x245152E4, 0x24510000),
    (0x3EED50, 0x3C020057, 0x3C020059, 0x3EED58, 0x245152E4, 0x24510000),
    (0x3EEE0C, 0x3C020057, 0x3C020059, 0x3EEE14, 0x245152E4, 0x24510000),
)


def make_boot(elf, payload, symbols):
    if hashlib.sha256(elf.data).hexdigest() != ELF_SHA256:
        raise ValueError('El ejecutable no corresponde a Digimon USA verificado.')
    data = bytearray(elf.data)
    def patch(address, old, new):
        if elf.read_virtual(address, 4) != struct.pack('<I', old):
            raise ValueError(f'Código inesperado en {address:08X}; no se aplica el hook.')
        for start, offset, length, _ in elf.segments:
            if start <= address < start+length:
                struct.pack_into('<I', data, offset+address-start, new)
                return
        raise ValueError('Dirección fuera del ejecutable.')
    # Leave the BSS clear end unchanged; reserve the new segment before any
    # allocation through SetupHeap and libkernel's independent sbrk break.
    patch(0x1001D0, 0x3C040057, 0x3C040059)
    patch(0x1001D8, 0x248452E4, 0x24840000)
    patch(0x4DC5CC, 0x005752E4, BASE+RESERVE)
    for high, old_high, new_high, low, old_low, new_low in ARENA_REFERENCES:
        patch(high, old_high, new_high)
        patch(low, old_low, new_low)
    for name, (address, words) in HOOKS.items():
        patch(address, words[0], jump(symbols[name]))
        patch(address+4, words[1], 0)
    phoff = struct.unpack_from('<I', data, 28)[0]
    size, count = struct.unpack_from('<HH', data, 42)
    if (phoff, size, count) != (52, 32, 1) or any(data[84:116]):
        raise ValueError('La tabla de segmentos no permite reservar memoria de forma conocida.')
    if len(elf.segments) != 1 or elf.segments[0][0]+elf.segments[0][3] > BASE:
        raise ValueError('La reserva colisiona con el juego.')
    if not payload or len(payload) > RESERVE:
        raise ValueError('El adaptador excede la reserva.')
    offset = align(len(data), 16)
    data.extend(bytes(offset-len(data)))
    data.extend(payload)
    struct.pack_into('<8I', data, 84, 1, offset, BASE, BASE, len(payload), RESERVE, 7, 16)
    struct.pack_into('<H', data, 44, 2)
    return bytes(data)


def build(iso, output):
    report, elf = inspect_disc(iso)
    if report['pcsx2_crc'] != CRC or report['elf_sha256'] != ELF_SHA256:
        raise ValueError('Selecciona Digimon Rumble Arena 2 USA SLUS-21067 / 568A5C78.')
    compiler = shutil.which('clang')
    if compiler is None:
        raise ValueError('La preparación del adaptador requiere clang con soporte MIPS.')
    output = Path(output)
    if (output/'adapter.json').exists():
        raise ValueError('Ya existe un adaptador en esa carpeta; usa otra revisión.')
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent
    flags = ['--target=mipsel-none-elf', '-march=mips3', '-mabi=32', '-mno-abicalls',
             '-fno-pic', '-G0', '-msoft-float', '-ffreestanding', '-fno-builtin',
             '-fno-stack-protector', '-O2', '-c']
    objects = []
    for name in ('entry.S', 'netpad4.c'):
        obj = output/(Path(name).stem+'.o')
        subprocess.run([compiler, *flags, str(root/'digimon_hook'/name), '-o', str(obj)], check=True)
        objects.append(obj)
    payload, symbols = link(objects, BASE, RESERVE)
    shared = symbols['g_np4']
    if (not BASE <= shared <= BASE+RESERVE-SHARED_SIZE or
            struct.unpack_from('<III', payload, shared-BASE) != (MAGIC, 1, SHARED_SIZE)):
        raise ValueError('El layout del adaptador no coincide con el driver.')
    boot = make_boot(elf, payload, symbols)
    boot_path = output/'Digimon-netplay.elf'
    boot_path.write_bytes(boot)
    code_size = shared-BASE
    metadata = {'schema': 1, 'adapter': ADAPTER, 'game': 'digimon-rumble-arena-2',
        'experimental': True, 'online_verified': False, 'hash_kind': 'inputs-only',
        'arena_reservation': 2,
        'pad_layout': 'port2',
        'source_serial': report['serial'], 'source_crc': CRC, 'source_elf_sha256': ELF_SHA256,
        'disc_sha256': sha256_file(iso), 'disc_path': str(Path(iso).resolve()),
        'boot_path': str(boot_path.resolve()), 'boot_sha256': hashlib.sha256(boot).hexdigest(),
        'boot_crc': pcsx2_crc(boot), 'payload_base': BASE, 'reserve_size': RESERVE,
        'shared_base': shared, 'shared_size': SHARED_SIZE, 'code_size': code_size,
        'code_sha256': hashlib.sha256(payload[:code_size]).hexdigest(), 'symbols': symbols}
    (output/'adapter.json').write_text(json.dumps(metadata, indent=2)+'\n')
    (output/'profiles').mkdir(exist_ok=True)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    parser.add_argument('--output', type=Path, default=Path('build/digimon/adapter-v1'))
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.iso, args.output), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')
