"""Read PS2 boot identification from plain ISO9660 images without mounting them.

Only small directory records, SYSTEM.CNF and the boot ELF are read. The image
is always opened read-only; no extracted game files need to be distributed.
"""
import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path


BLOCK = 2048
MAX_ELF = 32 * 1024 * 1024


def pcsx2_crc(data):
    """PCSX2 ElfObject::GetCRC: XOR complete little-endian u32 words, not CRC32."""
    result = 0
    for (word,) in struct.iter_unpack('<I', data[:len(data)//4*4]):
        result ^= word
    return f'{result:08X}'


@dataclass(frozen=True)
class Entry:
    name: str
    extent: int
    size: int
    directory: bool


class IsoImage:
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        self.file = self.path.open('rb')
        try:
            self.file.seek(0, 2)
            self.size = self.file.tell()
            for sector in range(16, 80):
                descriptor = self._read(sector*BLOCK, BLOCK)
                if descriptor[1:6] != b'CD001' or descriptor[6] != 1:
                    raise ValueError('La imagen no es un ISO9660 de sectores de 2048 bytes.')
                if descriptor[0] == 1:
                    if struct.unpack_from('<H', descriptor, 128)[0] != BLOCK:
                        raise ValueError('Tamaño de sector no compatible.')
                    self.volume_size = struct.unpack_from('<I', descriptor, 80)[0]*BLOCK
                    if self.volume_size > self.size or self.volume_size < 17*BLOCK:
                        raise ValueError('La imagen está truncada o su tamaño es inválido.')
                    self.root = self._record(descriptor, 156)
                    if not self.root.directory:
                        raise ValueError('Directorio raíz ISO9660 inválido.')
                    return self
                if descriptor[0] == 255:
                    break
            raise ValueError('No se encontró el descriptor primario ISO9660.')
        except BaseException:
            self.file.close()
            self.file = None
            raise

    def __exit__(self, *args):
        self.file.close()

    def _read(self, offset, size):
        if offset < 0 or size < 0 or offset+size > getattr(self, 'volume_size', self.size):
            raise ValueError('Referencia fuera de la imagen ISO.')
        self.file.seek(offset)
        data = self.file.read(size)
        if len(data) != size:
            raise ValueError('Lectura incompleta de la imagen ISO.')
        return data

    def _record(self, data, offset):
        if offset+34 > len(data):
            raise ValueError('Entrada ISO9660 truncada.')
        length, name_size = data[offset], data[offset+32]
        if length < 34 or offset+length > len(data) or 33+name_size > length:
            raise ValueError('Entrada ISO9660 inválida.')
        if data[offset+25] & 0x80:
            raise ValueError('Archivos ISO9660 multi-extent no compatibles.')
        name = data[offset+33:offset+33+name_size].decode('ascii')
        return Entry(name.split(';')[0].upper(), struct.unpack_from('<I', data, offset+2)[0],
                     struct.unpack_from('<I', data, offset+10)[0], bool(data[offset+25] & 2))

    def _entries(self, directory):
        if directory.size > 4*1024*1024:
            raise ValueError('Directorio ISO9660 demasiado grande.')
        data = self._read(directory.extent*BLOCK, directory.size)
        offset = 0
        while offset < len(data):
            length = data[offset]
            if length == 0:
                offset = (offset//BLOCK+1)*BLOCK
                continue
            if offset % BLOCK + length > BLOCK:
                raise ValueError('Entrada de directorio cruza el límite de un sector.')
            yield self._record(data, offset)
            offset += length

    def read_file(self, name, limit=MAX_ELF):
        parts = name.replace('\\', '/').strip('/').split('/')
        if any(part in ('', '.', '..') for part in parts):
            raise ValueError('Ruta interna de ISO inválida.')
        entry = self.root
        for part in parts:
            if not entry.directory:
                raise ValueError('La ruta interna no corresponde a un directorio.')
            target = part.split(';')[0].upper()
            entry = next((item for item in self._entries(entry) if item.name == target), None)
            if entry is None:
                raise ValueError(f'No se encontró {name} dentro de la ISO.')
        if entry.directory or entry.size > limit:
            raise ValueError(f'{name} es un directorio o supera el límite de lectura.')
        return self._read(entry.extent*BLOCK, entry.size)


class ElfImage:
    def __init__(self, data):
        self.data = data
        if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
            raise ValueError('El ejecutable no es ELF32 little-endian.')
        if struct.unpack_from('<H', data, 18)[0] != 8:
            raise ValueError('El ejecutable ELF no es MIPS.')
        self.entry = struct.unpack_from('<I', data, 24)[0]
        phoff = struct.unpack_from('<I', data, 28)[0]
        phsize, phcount = struct.unpack_from('<HH', data, 42)
        if phsize != 32 or not phcount or phoff+phsize*phcount > len(data):
            raise ValueError('Tabla de segmentos ELF inválida.')
        self.segments = []
        for i in range(phcount):
            kind, offset, address, _, size, memory, _, _ = struct.unpack_from('<8I', data, phoff+i*phsize)
            if kind == 1:
                if offset+size > len(data) or size > memory or address+memory > 0x100000000:
                    raise ValueError('Segmento ELF inválido.')
                self.segments.append((address, offset, size, memory))

    def read_virtual(self, address, size):
        if size < 0:
            raise ValueError('Tamaño inválido.')
        for start, offset, length, _ in self.segments:
            if start <= address and address+size <= start+length:
                return self.data[offset+address-start:offset+address-start+size]
        raise ValueError('La dirección no pertenece a los datos del ejecutable ELF.')


def inspect_disc(path):
    with IsoImage(path) as iso:
        system = iso.read_file('SYSTEM.CNF', limit=4096).decode('ascii')
        boot = re.search(r'^\s*BOOT2\s*=\s*cdrom0:\\?([^\r\n]+)', system, re.MULTILINE | re.IGNORECASE)
        if not boot:
            raise ValueError('SYSTEM.CNF no contiene un BOOT2 de PS2 reconocido.')
        executable = boot[1].strip().replace('\\', '/').lstrip('/').split(';')[0]
        data = iso.read_file(executable)
    elf = ElfImage(data)
    name = executable.rsplit('/', 1)[-1]
    match = re.fullmatch(r'([A-Z]{4})_(\d{3})\.(\d{2})', name.upper())
    serial = f'{match[1]}-{match[2]}{match[3]}' if match else None
    return {'serial': serial, 'boot': executable, 'elf_size': len(data),
            'elf_sha256': hashlib.sha256(data).hexdigest(), 'pcsx2_crc': pcsx2_crc(data),
            'elf_entry': f'0x{elf.entry:08X}'}, elf
