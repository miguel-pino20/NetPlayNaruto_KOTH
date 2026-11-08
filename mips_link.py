"""Small strict ELF32/MIPS REL linker for the freestanding D.O.N payload.

Supports only the relocations emitted by its pinned compiler flags. Unknown
relocations and unresolved symbols fail the build instead of producing a patch.
"""
import struct
from pathlib import Path


def align(value, boundary):
    if boundary <= 0 or boundary & (boundary-1):
        raise ValueError('Invalid ELF section alignment')
    return (value+boundary-1) & -boundary


def signed16(value):
    return (value & 0x7fff)-(value & 0x8000)


class Object:
    def __init__(self, path):
        self.path, self.data = Path(path), Path(path).read_bytes()
        b = self.data
        if b[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<HH', b, 16) != (1, 8):
            raise ValueError('Expected little-endian MIPS ELF relocatable object')
        off = struct.unpack_from('<I', b, 32)[0]
        size, count, names = struct.unpack_from('<HHH', b, 46)
        if size != 40 or off+size*count > len(b):
            raise ValueError('Invalid object section table')
        rows = [struct.unpack_from('<10I', b, off+i*40) for i in range(count)]
        strings = b[rows[names][4]:rows[names][4]+rows[names][5]]
        self.sections = []
        self.symbols = {}
        for index, r in enumerate(rows):
            name = strings[r[0]:].split(b'\0')[0].decode()
            self.sections.append({'index': index, 'name': name, 'type': r[1], 'flags': r[2],
                                  'offset': r[4], 'size': r[5], 'link': r[6], 'info': r[7],
                                  'align': r[8] or 1, 'entsize': r[9]})
            if r[1] != 8 and r[4]+r[5] > len(b):
                raise ValueError('Truncated object section')
        for section in self.sections:
            if section['type'] == 2:
                if section['entsize'] != 16 or section['size'] % 16:
                    raise ValueError('Invalid object symbol table')
                names_section = self.sections[section['link']]
                names_data = b[names_section['offset']:names_section['offset']+names_section['size']]
                table = []
                for pos in range(section['offset'], section['offset']+section['size'], 16):
                    name, value, _, info, _, shndx = struct.unpack_from('<IIIBBH', b, pos)
                    table.append({'name': names_data[name:].split(b'\0')[0].decode(),
                                  'value': value, 'info': info, 'shndx': shndx})
                self.symbols[section['index']] = table


def link(paths, base, limit):
    objects = [Object(path) for path in paths]
    payload = bytearray()
    for obj in objects:
        for section in obj.sections:
            if section['flags'] & 2 and section['name'] not in ('.reginfo', '.MIPS.abiflags'):
                if section['type'] not in (1, 8):
                    raise ValueError(f"Unsupported allocated section: {section['name']}")
                offset = align(base+len(payload), section['align'])-base
                section['address'] = base+offset
                payload.extend(bytes(offset-len(payload)))
                payload.extend(bytes(section['size']) if section['type'] == 8 else
                               obj.data[section['offset']:section['offset']+section['size']])
    if len(payload) > limit:
        raise ValueError('The hook exceeds its reserved memory')
    globals_ = {}

    def defined(obj, symbol):
        idx = symbol['shndx']
        if idx == 0xfff1:
            return symbol['value']
        if idx >= len(obj.sections) or 'address' not in obj.sections[idx]:
            raise ValueError(f"Unallocated symbol {symbol['name']}")
        return obj.sections[idx]['address']+symbol['value']

    for obj in objects:
        for table in obj.symbols.values():
            for symbol in table:
                if symbol['shndx'] and symbol['info'] >> 4 in (1, 2):
                    name = symbol['name']
                    if name in globals_:
                        raise ValueError(f'Duplicate symbol {name}')
                    globals_[name] = defined(obj, symbol)
    for obj in objects:
        for reloc in obj.sections:
            if reloc['type'] not in (4, 9):
                continue
            target = obj.sections[reloc['info']]
            if 'address' not in target:
                continue
            if reloc['type'] != 9 or reloc['entsize'] != 8:
                raise ValueError('Only MIPS REL relocations are supported')
            table = obj.symbols[reloc['link']]
            pending = {}
            for pos in range(reloc['offset'], reloc['offset']+reloc['size'], 8):
                offset, info = struct.unpack_from('<II', obj.data, pos)
                symbol_index, kind = info >> 8, info & 255
                symbol = table[symbol_index]
                value = defined(obj, symbol) if symbol['shndx'] else globals_.get(symbol['name'])
                if value is None:
                    raise ValueError(f"Unresolved symbol {symbol['name']}")
                if offset+4 > target['size']:
                    raise ValueError('Relocation outside section')
                p = target['address']-base+offset
                word = struct.unpack_from('<I', payload, p)[0]
                if kind == 0:
                    continue
                if kind == 2:  # R_MIPS_32
                    word = (word+value) & 0xffffffff
                elif kind == 4:  # R_MIPS_26
                    address = value+((word & 0x3ffffff)<<2)
                    if address & 3 or (address >> 28) != ((base+p+4) >> 28):
                        raise ValueError('MIPS jump target is not reachable')
                    word = (word & 0xfc000000) | ((address >> 2) & 0x3ffffff)
                elif kind == 5:  # R_MIPS_HI16: paired addend supplied by LO16
                    pending.setdefault(symbol_index, []).append((p, word))
                    continue
                elif kind == 6:  # R_MIPS_LO16
                    low = signed16(word)
                    for high_pos, high in pending.pop(symbol_index, []):
                        address = value+((high & 65535)<<16)+low
                        fixed = (high & 0xffff0000) | (((address+0x8000)>>16) & 65535)
                        struct.pack_into('<I', payload, high_pos, fixed)
                    word = (word & 0xffff0000) | ((value+low) & 65535)
                else:
                    raise ValueError(f'Unsupported MIPS relocation {kind}')
                struct.pack_into('<I', payload, p, word)
            if pending:
                raise ValueError('Unpaired MIPS HI16 relocation')
    return bytes(payload), globals_
