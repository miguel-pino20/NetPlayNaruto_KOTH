"""Diagnostic for two isolated D.O.N instances; never enables production online.

Uses the real UDP Node protocol and snapshots both emulators at identical input
barriers. RAM differences are evidence to investigate, not a gameplay checksum.
"""
import argparse
import hashlib
import itertools
import json
import struct
import time
import zipfile
from pathlib import Path

from don_core import DonCore, restore_profile
from node import Node
from pine import Pine
from wire import IDLE_PAD


def scripted_pad(frame, slot):
    # Start leaves Organícense; subsequent Circle presses confirm both players
    # and the host's following menus. The report records this exact schedule.
    events = [(20, 0, 3), (120, 0, 13), (120, 1, 13),
              (240, 0, 13), (360, 0, 13), (480, 0, 13)]
    raw = bytearray(IDLE_PAD)
    pressed = 0
    for start, player, bit in events:
        if player == slot and start <= frame < start+3:
            pressed |= 1 << bit
    if frame >= 600:
        # Different actions from each player exercise the assigned network slot.
        phase = frame-600
        direction = (5 if slot == 0 else 7) if phase % 240 < 150 else (7 if slot == 0 else 5)
        pressed |= 1 << direction
        if (phase+slot*7) % 17 < 3:
            pressed |= 1 << 15  # Square attack
        if (phase+slot*19) % 61 < 3:
            pressed |= 1 << 13  # Circle attack
        if (phase+slot*23) % 97 < 3:
            pressed |= 1 << 14  # Cross jump
    struct.pack_into('<H', raw, 2, 0xffff ^ pressed)
    for bit, byte in {5: 8, 7: 9, 4: 10, 6: 11, 12: 12, 13: 13, 14: 14, 15: 15}.items():
        if pressed & (1 << bit):
            raw[byte] = 255
    return bytes(raw)


class DiagnosticCore:
    """Stop exactly before limit; deterministic controls replace physical input."""
    def __init__(self, core, slot, limit, physical=False):
        self.core, self.slot, self.limit, self.physical = core, slot, limit, physical
        self.pending = {s: {} for s in range(2)}

    def captured(self, first, limit):
        return {frame: (raw if self.physical else scripted_pad(frame, self.slot), frame)
                for frame, (raw, _) in self.core.captured(first, limit).items()}

    def publish(self, slot, frames):
        self.core.publish(slot, {f: value for f, value in frames.items() if f < self.limit})
        self.pending[slot].update({f: value for f, value in frames.items() if f >= self.limit})

    def extend(self, limit):
        if limit <= self.limit:
            raise ValueError('Los puntos de comparación deben avanzar.')
        self.limit = limit
        for slot, frames in self.pending.items():
            ready = {f: value for f, value in frames.items() if f < limit}
            self.core.publish(slot, ready)
            for frame in ready:
                del frames[frame]

    def hashes(self, first, limit):
        return self.core.hashes(first, limit)  # deliberately input-only


def snapshot(core, directory, destination, timeout=20):
    """Use a free save slot and remove only the new diagnostic copy afterward."""
    directory, destination = Path(directory), Path(destination)
    before = set(directory.glob('*.p2s'))
    slot = next((n for n in range(9, -1, -1)
                 if not any(directory.glob(f'*.{n:02}.p2s'))), None)
    if slot is None:
        raise ValueError('No hay ranuras libres para la comparación.')
    core.pine.save_state(slot)
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        for path in set(directory.glob(f'*.{slot:02}.p2s'))-before:
            try:
                data = path.read_bytes()
                import io
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if archive.testzip() is not None:
                        continue
                    ram = archive.read('eeMemory.bin')
                    if len(ram) != 32*1024*1024:
                        raise ValueError('Tamaño de RAM inesperado.')
                    preview = archive.read('Screenshot.png') if 'Screenshot.png' in archive.namelist() else None
                with destination.open('xb') as output:
                    output.write(data)
                if preview:
                    destination.with_suffix('.png').write_bytes(preview)
                path.unlink()
                return ram
            except (OSError, zipfile.BadZipFile, EOFError):
                pass  # PCSX2 writes asynchronously.
        time.sleep(0.05)
    raise ValueError('No llegó el estado completo para comparar.')


def compare_ram(left, right):
    if len(left) != len(right) or len(left) != 32*1024*1024:
        raise ValueError('Se requieren dos imágenes completas de RAM EE.')
    result = {}
    for name, start, end in [('ee_ram', 0, len(left)),
                             ('candidate_globals', 0x4c9d80, 0x5a6800),
                             ('candidate_heap', 0x5b6800, 0x1f00000)]:
        a, b = left[start:end], right[start:end]
        pages = [start+i for i in range(0, len(a), 4096) if a[i:i+4096] != b[i:i+4096]]
        first = list(itertools.islice((start+i for i, (x, y) in enumerate(zip(a, b)) if x != y), 32)) if pages else []
        result[name] = {'equal': a == b, 'sha256': [hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest()],
                        'different_pages': len(pages), 'first_different_addresses': [hex(p) for p in first]}
    return result


def run(adapter, profiles, sessions, checkpoints, output, physical=False, timeout=90):
    if (len(sessions) != 2 or len({s['pine_slot'] for s in sessions}) != 2 or
            not checkpoints or checkpoints != sorted(set(checkpoints)) or checkpoints[0] < 1):
        raise ValueError('Se requieren dos instancias distintas y puntos crecientes positivos.')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    metadata = json.loads(Path(adapter).read_text())
    connections, cores, nodes, wrappers, temporary_states = [], [], [], [], []
    report = {'online_verified': False, 'transport': 'udp-loopback', 'players': 2,
              'hash_kind': 'inputs-only', 'physical_controls': physical, 'checkpoints': [],
              'verdict': 'inputs_test_only_gameplay_not_certified',
              'pine_slots': [s['pine_slot'] for s in sessions],
              'note': 'Raw RAM includes asynchronous timers, devices and rendering; '
                      'differences alone do not establish a gameplay divergence.'}
    try:
        for session in sessions:
            if Path(session['adapter']).resolve() != Path(adapter).resolve():
                raise ValueError('La instancia usa otro adaptador.')
            pine = Pine(session['pine_slot']).connect()
            connections.append(pine)
            core = DonCore(pine, metadata)
            if pine.version() != 'PCSX2 v2.8.2':
                raise ValueError('Esta prueba requiere la versión de PCSX2 de las capturas: v2.8.2.')
            core, detail = restore_profile(core, profiles, Path(session['data_path'])/'PCSX2/savestates', 2)
            cores.append(core)
            state_sha = json.loads(Path(detail['profile']).read_text())['state_sha256']
            temporary_states.append((Path(detail['state_slot_path']), state_sha))
            print(json.dumps({'restored': session['pine_slot'], **detail}), flush=True)
        for slot, core in enumerate(cores):
            wrapper = DiagnosticCore(core, slot, checkpoints[0], physical)
            wrappers.append(wrapper)
            host = None if slot == 0 else nodes[0].sock.getsockname()
            node = Node(wrapper, slot+1, slot, 0, [0, 1], bind='127.0.0.1', host=host,
                        delay=3, first_capture=1, tag=metadata['boot_sha256'][:16],
                        roster_locked=True, generic=True)
            node.sel_sync = False
            nodes.append(node)
        nodes[0].add_expected_peer(2, 1, nodes[1].sock.getsockname())
        report['udp_addresses'] = [list(n.sock.getsockname()) for n in nodes]
        released = False
        for index, target in enumerate(checkpoints):
            if index:
                for wrapper in wrappers:
                    wrapper.extend(target)
            deadline, next_log = time.monotonic()+timeout, time.monotonic()
            while time.monotonic() < deadline:
                for node in nodes:
                    node.pump()
                if not released and all(n.started for n in nodes) and all(min(n.published.values()) >= 1 for n in nodes):
                    for core in cores:
                        core.release()
                    released = True
                frames = [core.get('frame') for core in cores]
                if any(core.get('abort') for core in cores):
                    raise ValueError('Un emulador abortó la barrera de mandos.')
                if any(node.desync is not None for node in nodes):
                    raise ValueError('Los hashes de entradas difieren.')
                if frames == [target, target] and all(c.get('status') == 2 for c in cores):
                    break
                if time.monotonic() >= next_log:
                    print(json.dumps({'target': target, 'frames': frames, 'started': [n.started for n in nodes]}), flush=True)
                    next_log = time.monotonic()+10
                time.sleep(0.001)
            else:
                raise ValueError(f'No se llegó a la barrera {target}; fotogramas {frames}.')
            memory = [snapshot(c, Path(s['data_path'])/'PCSX2/savestates', output/f'frame-{target}-p{i+1}.p2s')
                      for i, (c, s) in enumerate(zip(cores, sessions))]
            point = {'frame': target, 'input_hashes_checked': nodes[0].checked,
                     'ram_comparison': compare_ram(*memory)}
            report['checkpoints'].append(point)
            (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps({'checkpoint': target, 'input_hashes_checked': nodes[0].checked,
                              'globals_equal': point['ram_comparison']['candidate_globals']['equal']}), flush=True)
        report['completed'] = True
    except BaseException as error:
        report.update(completed=False, error=str(error))
        raise
    finally:
        for core in cores:
            try:
                core.stop()
            except Exception:
                pass
        for node in nodes:
            node.close()
        for pine in connections:
            pine.close()
        for path, expected_sha in temporary_states:
            # Only the exact copy made by this run, still byte-identical to the
            # source profile. Keep a file if the emulator/user changed it.
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha:
                path.unlink()
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter', type=Path, default=Path('build/don/adapter.json'))
    parser.add_argument('--profiles', type=Path, default=Path('build/don/profiles'))
    parser.add_argument('--sessions', type=Path, nargs=2, required=True)
    parser.add_argument('--checkpoints', type=int, nargs='+', default=[1, 90, 180, 360, 720])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--physical', action='store_true')
    args = parser.parse_args()
    result = run(args.adapter, args.profiles, [json.loads(p.read_text()) for p in args.sessions],
                 args.checkpoints, args.output, args.physical)
    print(json.dumps({'completed': result['completed'], 'report': str(args.output/'report.json')}))
