"""PINE driver for the experimental four-pad D.O.N input barrier."""
import argparse
import hashlib
import json
import struct
import time
import zipfile
from pathlib import Path

from build_don import BASE, RESERVE, SHARED_SIZE, jump
from don_adapter import PAD_COUNT, PAD_INITIALIZED, PAD_RECORDS, PAD_STRIDE, MULTITAP_MODE, read_bytes
from pine import Pine, PineError
from wire import IDLE_PAD


HEADER = {'magic': 0, 'version': 4, 'size': 8, 'active': 12, 'abort': 16,
          'hold': 20, 'status': 24, 'local_slot': 28, 'frame': 32, 'captures': 36,
          'stalls': 40, 'missing': 44, 'hash_kind': 48, 'players': 52}
OUT, INPUTS, HASH, RING, ENTRY = 0x40, 0x1040, 0x5040, 128, 32


class DonCore:
    max_players = 4
    adapter_id = 'don-experimental-input-v1'
    simulation_hashes = False  # make_node must reject this until game determinism is verified

    def __init__(self, pine, metadata):
        self.pine, self.meta = pine, metadata
        self.base = metadata['shared_base']
        if (metadata.get('schema') != 1 or metadata.get('payload_base') != BASE or
                metadata.get('reserve_size') != RESERVE or metadata.get('shared_size') != SHARED_SIZE or
                not BASE <= self.base <= BASE+RESERVE-SHARED_SIZE):
            raise ValueError('Metadatos del adaptador inválidos.')
        if pine.game_crc() not in (metadata['boot_crc'], metadata['source_crc']):
            raise ValueError('El juego abierto no coincide con este ejecutable experimental.')
        size = metadata['code_size']
        if not 0 < size <= self.base-BASE:
            raise ValueError('Rango de código inválido.')
        if hashlib.sha256(read_bytes(pine, BASE, size)).hexdigest() != metadata['code_sha256']:
            raise ValueError('PCSX2 no tiene cargado el ejecutable experimental de esta compilación.')
        if pine.read(0x138B14) != jump(metadata['symbols']['np4_poll_entry'], call=True):
            raise ValueError('El hook de lectura de mandos no está instalado.')
        if (pine.read(0x118E38) != jump(metadata['symbols']['np4_read_entry']) or pine.read(0x118E3C) != 0):
            raise ValueError('El hook de aplicación de controles no está instalado.')
        if [self.get(key) for key in ('magic', 'version', 'size', 'hash_kind')] != [0x34504E44, 1, SHARED_SIZE, 1]:
            raise ValueError('El bloque compartido de D.O.N no coincide con el protocolo.')
        self.capacity = self.get('players') or 4
        if self.capacity not in (2, 3, 4):
            raise ValueError('La cantidad de jugadores guardada no es válida.')

    def get(self, key):
        return self.pine.read(self.base+HEADER[key])

    def put(self, key, value):
        self.pine.write(self.base+HEADER[key], value)

    def write_bytes(self, address, data):
        if address < self.base or address+len(data) > self.base+SHARED_SIZE:
            raise ValueError('Escritura fuera del bloque compartido.')
        ops = []
        offset = 0
        while offset < len(data):
            width = next(n for n in (8, 4, 2, 1) if n <= len(data)-offset)
            ops.append(('w', address+offset, int.from_bytes(data[offset:offset+width], 'little'), width))
            offset += width
        for first in range(0, len(ops), 100):
            self.pine.batch(ops[first:first+100])

    def arm(self, capacity=4):
        if capacity not in (2, 3, 4):
            raise ValueError('La sesión debe tener entre 2 y 4 jugadores.')
        if self.get('active'):
            raise ValueError('Ya hay una prueba activa; detenla antes de empezar otra.')
        if self.pine.batch([('r', a, 4) for a in (MULTITAP_MODE, PAD_COUNT, PAD_INITIALIZED)]) != [1, 4, 1]:
            raise ValueError('D.O.N debe haber inicializado los cuatro puestos del Multitap del puerto 1.')
        states = self.pine.batch([('r', PAD_RECORDS+s*PAD_STRIDE, 2) for s in range(4)] +
                                [('r', PAD_RECORDS+s*PAD_STRIDE+4, 2) for s in range(4)])
        if states != [99]*4+[6]*4:
            raise ValueError('Espera a que los cuatro mandos terminen de inicializarse.')
        self.write_bytes(self.base+OUT, bytes(SHARED_SIZE-OUT))
        for key, value in {'abort': 0, 'hold': 1, 'status': 0, 'local_slot': 0,
                           'frame': 0, 'captures': 0, 'stalls': 0, 'missing': 15,
                           'players': capacity}.items():
            self.put(key, value)
        self.capacity = capacity
        # The game keeps four emulated Multitap sockets. Inactive NETWORK slots
        # receive neutral pads and never participate in the peer handshake.
        self._inactive(range(11))
        self.put('active', 1)

    def _inactive(self, frames):
        for slot in range(self.capacity, 4):
            self.publish(slot, {frame: (IDLE_PAD, 0) for frame in frames})

    def release(self):
        self.put('hold', 0)

    def frozen(self, capacity):
        return [self.get(key) for key in ('active', 'abort', 'hold', 'frame', 'captures', 'players')] == [1, 0, 1, 0, 1, capacity]

    def stop(self):
        self.put('abort', 1)
        self.put('hold', 0)
        self.put('active', 0)

    def captured(self, first, limit=64):
        result = {}
        for f in range(first, first+min(limit, RING)):
            address = self.base+OUT+(f % RING)*ENTRY
            if self.pine.read(address+24) != f+1:
                break
            data = read_bytes(self.pine, address, ENTRY)
            if struct.unpack_from('<I', data, 24)[0] != f+1:
                break
            result[f] = (data[:24], struct.unpack_from('<I', data, 28)[0])
        self._inactive(result)
        return result

    def publish(self, slot, frames):
        if type(slot) is not int or not 0 <= slot < 4:
            raise ValueError('Puesto fuera de P1–P4.')
        for frame, (raw, aux) in sorted(frames.items()):
            if not 0 <= frame < 0xffffffff or len(raw) != 24:
                raise ValueError('Entrada de mando inválida.')
            address = self.base+INPUTS+slot*RING*ENTRY+(frame % RING)*ENTRY
            self.write_bytes(address, raw)
            self.pine.write(address+28, aux & 0xffffffff)
            self.pine.write(address+24, frame+1)  # commit LAST

    def hashes(self, first, limit=64):
        """Debug input hashes only, NOT simulation state hashes."""
        result = {}
        for frame in range(first, first+min(limit, RING)):
            data = self.pine.read(self.base+HASH+(frame % RING)*8, 8)
            if data & 0xffffffff != frame+1:
                break
            result[frame] = data >> 32
        return result


def loopback(core, frames=120, delay=3, control=0, timeout=20, capacity=4, restored=False):
    """One physical pad -> chosen virtual pad, others neutral. Restores pads on exit."""
    if capacity not in (2, 3, 4) or not 1 <= delay <= 10 or not 1 <= frames <= 100000 or control not in range(capacity):
        raise ValueError('Parámetros de loopback inválidos.')
    armed = False
    try:
        if restored:
            if not core.frozen(capacity):
                raise ValueError('Carga el estado inicial congelado para esta cantidad de jugadores.')
            core.capacity = capacity
        else:
            core.arm(capacity)
        armed = True
        for slot in range(capacity):
            core.publish(slot, {f: (IDLE_PAD, 0) for f in range(delay+int(restored))})
        first, released = int(restored), False
        if restored:
            # Frame 0 was captured on the state creator's PC; ignore that pad.
            # Release only after neutral leading frames have been committed.
            core.release()
            released = True
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            for frame, (raw, aux) in core.captured(first, 64).items():
                target = frame+delay
                for slot in range(capacity):
                    core.publish(slot, {target: (raw if slot == control else IDLE_PAD, aux)})
                first = frame+1
            if first and not released:
                core.release()
                released = True
            if core.get('abort'):
                raise ValueError('El hook abortó la prueba; comprueba el mando físico 1A.')
            done = core.get('frame')
            if done >= frames:
                return {'frames': done, 'captured': first, 'virtual_player': control+1,
                        'players': capacity, 'delay': delay, 'restored': restored,
                        'hash_kind': 'inputs-only', 'online_verified': False}
            time.sleep(0.001)
        raise ValueError('La prueba no avanzó a tiempo. Reanuda PCSX2 si está pausado.')
    finally:
        if armed:
            core.stop()


def restore_profile(core, profiles, state_dir, capacity, timeout=20):
    """Load a validated profile via a new, unused PCSX2 save slot."""
    from don_profiles import select_profile
    if core.get('active'):
        raise ValueError('Hay una captura o prueba activa; termínala antes de restaurar el estado.')
    selected = select_profile(profiles, capacity, core.meta)
    directory = Path(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    slot = next((n for n in range(9, -1, -1) if not any(directory.glob(f'*.{n:02}.p2s'))), None)
    if slot is None:
        raise ValueError('No hay ranuras libres para probar sin sobrescribir otro estado.')
    name = f"{core.meta['source_serial']} ({core.pine.game_crc()}).{slot:02}.p2s"
    target = directory/name
    with Path(selected['state']).open('rb') as source, target.open('xb') as dest:
        while block := source.read(1024*1024):
            dest.write(block)
    try:
        core.pine.load_state(slot)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                loaded = DonCore(core.pine, core.meta)
                if loaded.frozen(capacity) and core.pine.status() == 0:
                    return loaded, {'profile': selected['manifest'], 'slot': slot,
                                    'state_slot_path': str(target.resolve())}
            except ValueError:
                pass  # Loading a state is asynchronous in some PCSX2 versions.
            time.sleep(0.05)
        raise ValueError('No se restauró el perfil. Comprueba la carpeta de estados y la instancia PINE.')
    except BaseException:
        try:
            core.stop()
        except (PineError, OSError):
            pass
        raise


def prepare_state(core, state_dir, output, capacity=4, slot=None, timeout=20):
    """Freeze the current screen and save a new snapshot without overwriting one."""
    state_dir, output = Path(state_dir), Path(output)
    if capacity not in (2, 3, 4) or (slot is not None and not 0 <= slot <= 9):
        raise ValueError('Cantidad de jugadores o ranura inválida.')
    if output.exists():
        raise ValueError('El estado de destino ya existe; no se sobrescribe.')
    state_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    before = set(state_dir.glob('*.p2s'))
    if slot is None:
        slot = next((n for n in range(9, -1, -1) if not any(state_dir.glob(f'*.{n:02}.p2s'))), None)
    if slot is None or any(state_dir.glob(f'*.{slot:02}.p2s')):
        raise ValueError('No hay una ranura libre para guardar sin sobrescribir estados anteriores.')
    armed = False
    try:
        core.arm(capacity)
        armed = True
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if core.get('captures') and core.get('status') == 2:
                break
            time.sleep(0.01)
        else:
            raise ValueError('El juego no llegó a la barrera. Reanuda la instancia experimental si está pausada.')
        core.pine.save_state(slot)
        while time.monotonic() < deadline:
            for candidate in state_dir.glob('*.p2s'):
                if candidate in before:
                    continue
                try:
                    with zipfile.ZipFile(candidate) as archive:
                        if archive.getinfo('eeMemory.bin').file_size != 32*1024*1024 or archive.testzip() is not None:
                            continue
                    with candidate.open('rb') as source, output.open('xb') as dest:
                        while block := source.read(1024*1024):
                            dest.write(block)
                    return {'path': str(output.resolve()), 'players': capacity, 'slot': slot,
                            'state_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                            'frozen_frame': 0, 'online_verified': False}
                except (zipfile.BadZipFile, KeyError):
                    continue
            time.sleep(0.05)
        raise ValueError('PCSX2 no generó un estado completo en la carpeta indicada.')
    finally:
        if armed:
            core.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prueba local del hook de cuatro mandos; no inicia online.')
    parser.add_argument('--adapter', type=Path, default=Path(__file__).resolve().parent/'build/don/adapter.json')
    parser.add_argument('--pine-slot', type=int, default=28011)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('stop')
    test = sub.add_parser('loopback')
    test.add_argument('--frames', type=int, default=120)
    test.add_argument('--player', type=int, choices=(1, 2, 3, 4), default=1)
    test.add_argument('--players', type=int, choices=(2, 3, 4), required=True)
    snapshot = sub.add_parser('prepare-state')
    snapshot.add_argument('--players', type=int, choices=(2, 3, 4), required=True)
    snapshot.add_argument('--state-dir', type=Path, required=True)
    snapshot.add_argument('--output', type=Path, required=True)
    restore = sub.add_parser('restore-test')
    restore.add_argument('--players', type=int, choices=(2, 3, 4), required=True)
    restore.add_argument('--profiles', type=Path, default=Path(__file__).resolve().parent/'build/don/profiles')
    restore.add_argument('--state-dir', type=Path, required=True)
    restore.add_argument('--frames', type=int, default=60)
    args = parser.parse_args(argv)
    pine = Pine(args.pine_slot, timeout=3)
    try:
        metadata = json.loads(args.adapter.read_text())
        pine.connect()
        core = DonCore(pine, metadata)
        if args.command == 'loopback':
            result = loopback(core, args.frames, control=args.player-1, capacity=args.players)
        elif args.command == 'prepare-state':
            result = prepare_state(core, args.state_dir, args.output, capacity=args.players)
        elif args.command == 'restore-test':
            core, selected = restore_profile(core, args.profiles, args.state_dir, args.players)
            result = {**loopback(core, args.frames, capacity=args.players, restored=True), **selected}
        elif args.command == 'stop':
            core.stop()
            result = {'stopped': True}
        else:
            result = {name: core.get(name) for name in HEADER}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, PineError) as error:
        parser.exit(1, str(error)+'\n')
    finally:
        pine.close()


if __name__ == '__main__':
    raise SystemExit(main())
