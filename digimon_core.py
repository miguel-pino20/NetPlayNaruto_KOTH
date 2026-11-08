"""Experimental Digimon four-pad driver, reusing the shared input-ring ABI."""
import hashlib

from build_don import jump
from build_digimon import BASE, RESERVE, SHARED_SIZE, MAGIC, ADAPTER, HOOKS, ARENA_REFERENCES
from don_adapter import read_bytes
from don_core import DonCore, HEADER, OUT
from digimon_adapter import CRC, PAD_OBJECTS, PAD_STRIDE
from game_adapters import validate_metadata


class DigimonCore(DonCore):
    max_players = 4
    adapter_id = ADAPTER
    simulation_hashes = False

    def __init__(self, pine, metadata):
        if validate_metadata(metadata).slug != 'digimon':
            raise ValueError('El perfil no pertenece a Digimon.')
        self.pine, self.meta, self.base = pine, metadata, metadata['shared_base']
        if pine.game_crc() not in (CRC, metadata['boot_crc']):
            raise ValueError('Abre Digimon Rumble Arena 2 USA antes de conectar.')
        size = metadata['code_size']
        if not 0 < size <= self.base-BASE:
            raise ValueError('El rango del adaptador Digimon es inválido.')
        if hashlib.sha256(read_bytes(pine, BASE, size)).hexdigest() != metadata['code_sha256']:
            raise ValueError('Falta el adaptador Digimon; arranca el ELF preparado o carga su estado inicial.')
        for name, (address, _) in HOOKS.items():
            if pine.batch([('r', address, 4), ('r', address+4, 4)]) != [jump(metadata['symbols'][name]), 0]:
                raise ValueError('Los hooks de Digimon no coinciden con el perfil.')
        reservation = [(address, expected)
                       for high, _, new_high, low, _, new_low in ARENA_REFERENCES
                       for address, expected in ((high, new_high), (low, new_low))]
        if pine.batch([('r', address, 4) for address, _ in reservation]) != [expected for _, expected in reservation]:
            raise ValueError('La reserva de memoria de Digimon no está corregida; reinicia con el ELF actualizado.')
        if [self.get(k) for k in ('magic', 'version', 'size', 'hash_kind')] != [MAGIC, 1, SHARED_SIZE, 1]:
            raise ValueError('El bloque de mandos Digimon es inválido.')
        self.capacity = self.get('players') or 4
        if self.capacity not in (2, 3, 4):
            raise ValueError('Cantidad de jugadores inválida.')

    def configure_players(self, capacity):
        """Select room seats while the shared four-seat snapshot is frozen."""
        if capacity not in (2, 3, 4) or not self.frozen(self.capacity):
            raise ValueError('Configura los jugadores solo con el estado inicial congelado.')
        if self.capacity not in (capacity, 4):
            raise ValueError('Se requiere el estado común de cuatro puestos.')
        self.capacity = capacity
        self.put('players', capacity)
        # The hook always waits for four sockets, including unoccupied seats.
        self._inactive(range(11))

    def arm(self, capacity=4):
        if capacity not in (2, 3, 4) or self.get('active'):
            raise ValueError('Selecciona 2–4 jugadores y termina la sesión anterior.')
        # Interleaved game objects: 1A=0, 2A=1, 2B=3, 2C=5.
        indices = (0, 1, 3, 5)
        ports = ((0, 0), (1, 0), (1, 1), (1, 2))
        ops = [('r', PAD_OBJECTS+index*PAD_STRIDE+offset, 4)
               for index in indices for offset in (0xD0, 0xD4, 0x200, 0xC0)]
        expected = [value for port, slot in ports for value in (port, slot, 4, 1)]
        if self.pine.batch(ops) != expected:
            raise ValueError('Inicializa 1A, 2A, 2B y 2C con Multitap solo en el puerto 2 antes de capturar.')
        if any(self.pine.batch([('r', PAD_OBJECTS+i*PAD_STRIDE+0xC0, 4) for i in (2, 4, 6, 7)])):
            raise ValueError('Desconecta los puestos sobrantes: 1B–1D y 2D; usa el ELF actualizado.')
        self.write_bytes(self.base+OUT, bytes(SHARED_SIZE-OUT))
        for key, value in {'abort': 0, 'hold': 1, 'status': 0, 'local_slot': 0,
                           'frame': 0, 'captures': 0, 'stalls': 0, 'missing': 15, 'players': capacity}.items():
            self.put(key, value)
        self.capacity = capacity
        self._inactive(range(11))
        self.put('active', 1)
