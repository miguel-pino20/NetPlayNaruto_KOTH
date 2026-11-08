"""Build a local experimental boot ELF from the user's unmodified D.O.N ISO.

It reserves 64 KiB ahead of heap initialization, libkernel's sbrk break and the
game's big pool, then places the hook there. No game bytes ship with the source.
"""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

from disc_image import inspect_disc, pcsx2_crc
from don_adapter import CRC, ELF_SHA256
from mips_link import align, link

BASE, RESERVE = 0x5A6800, 0x10000
SHARED_SIZE = 0x5440


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def jump(address, call=False):
    if address & 3 or not 0 <= address < 0x10000000:
        raise ValueError('Invalid MIPS jump address')
    return (0x0c000000 if call else 0x08000000) | address >> 2


def make_boot(elf, payload, symbols):
    if hashlib.sha256(elf.data).hexdigest() != ELF_SHA256:
        raise ValueError('El ejecutable no coincide con el perfil verificado de D.O.N.')
    data = bytearray(elf.data)

    def patch(address, old, new):
        expected = struct.pack('<I', old)
        if elf.read_virtual(address, 4) != expected:
            raise ValueError(f'La instrucción en {address:08X} no coincide con el perfil.')
        for start, offset, size, _ in elf.segments:
            if start <= address < start+size:
                struct.pack_into('<I', data, offset+address-start, new)
                return
        raise ValueError('Patch fuera del ejecutable')

    # Keep the ordinary BSS-clear end unchanged: the new segment is preinitialized.
    patch(0x1001D0, 0x3C04005A, 0x3C04005B)   # SetupHeap start: 5A6800 -> 5B6800
    patch(0x1365DC, 0x3C02005A, 0x3C02005B)   # reduce the requested big pool by 64 KiB too
    patch(0x3BC354, 0x005A6800, 0x005B6800)   # libkernel sbrk's independently initialized program break
    patch(0x138B14, 0x0C04E3EC, jump(symbols['np4_poll_entry'], call=True))
    patch(0x118E38, 0x0080382D, jump(symbols['np4_read_entry']))
    patch(0x118E3C, 0x24030070, 0)
    phoff = struct.unpack_from('<I', data, 28)[0]
    phsize, phcount = struct.unpack_from('<HH', data, 42)
    if (phsize, phcount) != (32, 2):
        raise ValueError('Tabla de segmentos inesperada.')
    last = struct.unpack_from('<8I', data, phoff+32)
    if last[0] != 1 or last[2] != BASE or last[4:6] != (0, 0):
        raise ValueError('El segundo segmento ya contiene datos.')
    if not payload or len(payload) > RESERVE:
        raise ValueError('Payload fuera de la reserva.')
    offset = align(len(data), 16)
    data.extend(bytes(offset-len(data)))
    data.extend(payload)
    struct.pack_into('<8I', data, phoff+32, 1, offset, BASE, BASE, len(payload), RESERVE, 7, 16)
    return bytes(data)


def build(iso, output):
    report, elf = inspect_disc(iso)
    if report['pcsx2_crc'] != CRC or report['elf_sha256'] != ELF_SHA256:
        raise ValueError('La ISO no contiene el ejecutable de D.O.N admitido.')
    compiler = shutil.which('clang')
    if compiler is None:
        raise ValueError('Falta clang con soporte MIPS para compilar el hook.')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    common = [compiler, '--target=mipsel-none-elf', '-march=mips3', '-mabi=32',
              '-mno-abicalls', '-fno-pic', '-G0', '-msoft-float', '-ffreestanding',
              '-fno-builtin', '-fno-stack-protector', '-O2', '-c']
    objects = []
    for name in ('entry.S', 'netpad4.c'):
        obj = output/(Path(name).stem+'.o')
        subprocess.run([*common, str(here/'don_hook'/name), '-o', str(obj)], check=True)
        objects.append(obj)
    payload, symbols = link(objects, BASE, RESERVE)
    shared = symbols['g_np4']-BASE
    if (not BASE <= symbols['g_np4'] <= BASE+RESERVE-SHARED_SIZE or
            struct.unpack_from('<III', payload, shared) != (0x34504E44, 1, SHARED_SIZE)):
        raise ValueError('El layout del hook no coincide con el protocolo de Python.')
    boot = make_boot(elf, payload, symbols)
    boot_path = output/'DON-loopback.elf'
    boot_path.write_bytes(boot)
    (output/'payload.bin').write_bytes(payload)
    text_end = min(symbols['g_np4'], symbols.get('np4_poll', BASE)+0x1000)
    metadata = {'schema': 1, 'adapter': 'don-experimental-input-v1',
                'experimental': True, 'online_verified': False, 'hash_kind': 'inputs-only',
                'source_serial': report['serial'], 'source_crc': CRC,
                'source_elf_sha256': ELF_SHA256,
                'disc_sha256': sha256_file(iso), 'disc_path': str(Path(iso).resolve()),
                'boot_path': str(boot_path.resolve()), 'boot_sha256': hashlib.sha256(boot).hexdigest(),
                'boot_crc': pcsx2_crc(boot), 'payload_base': BASE, 'reserve_size': RESERVE,
                'shared_base': symbols['g_np4'], 'shared_size': SHARED_SIZE,
                'code_size': text_end-BASE,
                'code_sha256': hashlib.sha256(payload[:text_end-BASE]).hexdigest(),
                'symbols': symbols}
    (output/'adapter.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'build/don')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.iso, args.output), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')
