"""Local four-emulator Digimon diagnostic using one physical pad.

P1 uses the already open PCSX2. Three temporary Flatpak profiles use different
PINE sockets, copied cards and loopback UDP. No Django account/room is created.
Input hashes are not a simulation-state checksum or an Internet certification.
"""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from uuid import uuid4

from digimon_core import DigimonCore
from digimon_adapter import PAD_OBJECTS
from don_dual_test import snapshot
from don_online import load_initial, stalled_details
from don_profiles import select_profile
from don_routing import BridgeSocket, PROTOCOL
from don_setup import latest_state_directory
from node import Node
from pine import Pine
from wire import IDLE_PAD


class LocalCore:
    def __init__(self, core, slot, limit=600, scripted=False):
        self.core, self.slot, self.limit = core, slot, limit
        self.scripted = scripted
        self.pending = {s: {} for s in range(4)}
        self.non_neutral = 0

    def captured(self, first, limit):
        result = {}
        for frame, (raw, aux) in self.core.captured(first, limit).items():
            if self.slot or self.scripted:
                # Confirm character, power and ready for the already-joined
                # guests, then leave only P1 under physical control.
                start = 30+self.slot*20
                raw = bytearray(IDLE_PAD)
                presses = (0, 180, 360, 660, 900) if self.scripted and self.slot == 0 else (0, 180, 360)
                if any(start+offset <= frame < start+offset+3 for offset in presses):
                    raw[3] &= ~0x40
                    raw[14] = 255
                if self.scripted and frame >= 1400:
                    phase = frame-1400+self.slot*31
                    buttons = [5 if (phase//120) % 2 == 0 else 7]
                    if phase % 37 < 3:
                        buttons.append(15)
                    if phase % 97 < 3:
                        buttons.append(14)
                    for bit in buttons:
                        raw[2+bit//8] &= ~(1 << (bit % 8))
                        raw[{5: 8, 7: 9, 14: 14, 15: 15}[bit]] = 255
                raw = bytes(raw)
            if raw != IDLE_PAD:
                self.non_neutral += 1
            result[frame] = raw, aux
        return result

    def publish(self, slot, frames):
        self.core.publish(slot, {f: v for f, v in frames.items() if f < self.limit})
        self.pending[slot].update({f: v for f, v in frames.items() if f >= self.limit})

    def hashes(self, first, limit):
        return self.core.hashes(first, limit)

    def extend(self, limit=0xffffffff):
        self.limit = limit
        for slot, frames in self.pending.items():
            ready = {f: v for f, v in frames.items() if f < limit}
            self.core.publish(slot, ready)
            for frame in ready:
                del frames[frame]


def prepare_child(metadata, source, target, slot):
    source, target = Path(source), Path(target)
    config = configparser.RawConfigParser(strict=False)
    config.optionxform = str
    if not config.read(source/'inis/PCSX2.ini'):
        raise ValueError('No se encontró la configuración habitual de PCSX2.')
    bios = Path(config.get('Folders', 'Bios', fallback='bios'))
    cards = Path(config.get('Folders', 'MemoryCards', fallback='memcards'))
    bios = bios if bios.is_absolute() else source/bios
    cards = cards if cards.is_absolute() else source/cards
    if not (bios/config.get('Filenames', 'BIOS')).is_file():
        raise ValueError('No se encontró la BIOS configurada.')
    target.mkdir(parents=True, exist_ok=False)
    data = target/'PCSX2'
    for folder in ('inis', 'memcards', 'savestates', 'gamesettings', 'inputprofiles', 'cache', 'logs'):
        (data/folder).mkdir(parents=True, exist_ok=True)
    for n in (1, 2):
        name = config.get('MemoryCards', f'Slot{n}_Filename', fallback='')
        enabled = config.getboolean('MemoryCards', f'Slot{n}_Enable', fallback=False)
        card = cards/name
        if enabled and name and card.is_file():
            dest = f'local-P{slot+1}-slot{n}.ps2'
            shutil.copyfile(card, data/'memcards'/dest)
            config.set('MemoryCards', f'Slot{n}_Filename', dest)
        elif enabled and name and card.is_dir():
            dest = f'local-P{slot+1}-slot{n}'
            shutil.copytree(card, data/'memcards'/dest)
            config.set('MemoryCards', f'Slot{n}_Filename', dest)
        else:
            config.set('MemoryCards', f'Slot{n}_Enable', 'false')
    settings = {
        'UI': {'SetupWizardIncomplete': 'false', 'PauseOnFocusLoss': 'false', 'StartFullscreen': 'false'},
        'EmuCore': {'EnablePINE': 'true', 'PINESlot': str(28011+slot), 'SaveStateOnShutdown': 'false',
                    'EnableCheats': 'false', 'McdFolderAutoManage': 'false'},
        'Achievements': {'Enabled': 'false'},
        'Pad': {'MultitapPort1': 'false', 'MultitapPort2': 'true'},
        'SPU2/Output': {'OutputMuted': 'true'},
        'Logging': {'EnableFileLogging': 'true', 'EnableEEConsole': 'true', 'EnableIOPConsole': 'true'},
    }
    for section, values in settings.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in values.items():
            config.set(section, key, value)
    for key in ('MainWindowGeometry', 'MainWindowState', 'DisplayWindowGeometry'):
        config.remove_option('UI', key)
    for key in list(config['Folders']):
        config.set('Folders', key, str(bios.resolve()) if key == 'Bios' else str((data/key.lower()).resolve()))
    config.set('Folders', 'MemoryCards', str((data/'memcards').resolve()))
    with (data/'inis/PCSX2.ini').open('w') as f:
        config.write(f, space_around_delimiters=True)
    # A loaded state restores host:Digimon-netplay.elf. Renaming the boot
    # breaks that lookup and makes PCSX2 lose the active ELF identity.
    boot = target/Path(metadata['boot_path']).name
    shutil.copyfile(metadata['boot_path'], boot)
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/'+str(os.getuid())))
    command = ['flatpak', 'run', f'--filesystem={target.resolve()}',
        f"--filesystem={Path(metadata['disc_path']).resolve()}:ro", f'--filesystem={bios.resolve()}:ro',
        f'--env=XDG_RUNTIME_DIR={runtime}/app/net.pcsx2.PCSX2',
        '--env=SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1']
    display = os.environ.get('WAYLAND_DISPLAY')
    if display and not display.startswith('/'):
        command.append(f'--env=WAYLAND_DISPLAY={runtime}/{display}')
    command += ['net.pcsx2.PCSX2', '-batch', '-nofullscreen', '-datapath', str(target.resolve()),
                '-elf', str(boot.resolve()), '-fastboot', '--', metadata['disc_path']]
    return {'slot': slot, 'pine_slot': 28011+slot, 'state_dir': str(data/'savestates'), 'command': command}


def ram_comparison(reference, other):
    report = {}
    for name, lo, hi in (('ee_ram', 0, 32*1024*1024), ('globals', 0x429380, 0x5752e4),
                         ('heap', 0x590000, 0x1f00000)):
        a, b = reference[lo:hi], other[lo:hi]
        different = [lo+i for i in range(0, len(a), 4096) if a[i:i+4096] != b[i:i+4096]]
        report[name] = {'equal': not different, 'different_pages': len(different),
                        'first_pages': [hex(i) for i in different[:12]]}
    return report


def run(output, seconds=180, checkpoint=600, scripted=False, checkpoints=None):
    points = sorted(set(checkpoints or [checkpoint]))
    if not points or any(not 0 < point < 0xffffffff for point in points):
        raise ValueError('Los puntos de comparación deben ser enteros positivos.')
    point_index = 0
    checkpoint = points[0]
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    metadata = json.loads(Path('build/digimon/adapter-v1/adapter.json').read_text())
    profile = select_profile('build/digimon/adapter-v1/profiles', 4, metadata)
    manifest = json.loads(Path(profile['manifest']).read_text())
    state = profile['state']
    source = Path.home()/'.var/app/net.pcsx2.PCSX2/config/PCSX2'
    sessions = [{'slot': 0, 'pine_slot': 28011, 'state_dir': latest_state_directory(28011)}]
    connections, cores, wrappers, nodes, processes = [], [], [], [], []
    report = {'players': 4, 'transport': 'udp-loopback-bridge', 'online_verified': False,
        'physical_slot': None if scripted else 0, 'seconds': seconds, 'checkpoint': checkpoint,
        'checkpoints': points, 'scripted': scripted,
        'gameplay_sync_certified': False, 'completed': False,
        'note': ('All inputs scripted.' if scripted else 'P1 physical; P2-P4 confirm character/power/ready then neutral.')+
                ' No remote ZeroTier or Django room is tested.'}
    def save():
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    def emit(data):
        print(json.dumps(data, ensure_ascii=False), flush=True)
    save()
    try:
        # Refuse unrelated instances instead of connecting to an old test's
        # socket while writing its state into a different temporary directory.
        for slot in (28012, 28013, 28014):
            probe = Pine(slot, timeout=.2)
            try:
                probe.connect()
            except Exception:
                pass
            else:
                raise ValueError(f'PINE {slot} ya está ocupado; cierra esa instancia antes de la prueba local.')
            finally:
                probe.close()
        # Back up the user's current P1 session before loading any shared state.
        pine = Pine(28011, timeout=3).connect()
        connections.append(pine)
        original = DigimonCore(pine, metadata)
        if original.get('active') or pine.status() != 0:
            raise ValueError('P1 debe estar ejecutándose sin otra sesión de netplay activa.')
        snapshot(original, sessions[0]['state_dir'], root/'P1-before-local.p2s')
        for slot in (1, 2, 3):
            session = prepare_child(metadata, source, root/f'P{slot+1}', slot)
            sessions.append(session)
            with (root/f'P{slot+1}'/'startup.log').open('xb') as log:
                process = subprocess.Popen(session['command'], stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True)
            processes.append(process)
            session['process_pid'] = process.pid
            emit({'launched': f'P{slot+1}', 'pine': session['pine_slot']})
        (root/'sessions.json').write_text(json.dumps(sessions, indent=2)+'\n')
        for index, session in enumerate(sessions):
            deadline = time.monotonic()+40
            while True:
                p = connections[0] if index == 0 else Pine(session['pine_slot'], timeout=.5)
                try:
                    if index:
                        p.connect()
                    if p.status() != 0 or p.game_crc() not in (metadata['source_crc'], metadata['boot_crc']):
                        raise ValueError('Esperando el arranque de Digimon.')
                    if index and p.read(PAD_OBJECTS+0x200) != 4:
                        raise ValueError('Esperando que Digimon inicialice el mando antes de cargar el estado.')
                    if index:
                        p.sock.settimeout(3)
                        p.timeout = 3
                    core = load_initial(p, metadata, manifest, state, session['state_dir'])
                    if index:
                        connections.append(p)
                    cores.append(core)
                    emit({'restored': f'P{index+1}', 'pine': session['pine_slot']})
                    break
                except Exception:
                    if index:
                        p.close()
                    if index == 0 or time.monotonic() >= deadline or processes[index-1].poll() is not None:
                        raise
                    time.sleep(.25)
        roster = []
        for slot in range(4):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            roster.append({'slot': slot, 'address': '127.0.0.1', 'port': port})
        room_id, epoch = str(uuid4()), str(uuid4())
        tag = hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',', ':')).encode()).hexdigest()[:16]
        for slot, core in enumerate(cores):
            wrapper = LocalCore(core, slot, checkpoint, scripted=scripted)
            wrappers.append(wrapper)
            bridge = BridgeSocket({'id': room_id, 'slot': slot, 'session_epoch': epoch,
                                   'manifest': manifest, 'players': roster})
            try:
                node = Node(wrapper, slot+1, slot, roster[slot]['port'], list(range(4)), sock=bridge,
                    host=None if slot == 0 else ('127.0.0.1', roster[0]['port']), delay=3,
                    tag=tag, epoch=epoch, first_capture=1, generic=True, roster_locked=True)
            except BaseException:
                bridge.close()
                raise
            node.sel_sync = False
            nodes.append(node)
        for slot in (1, 2, 3):
            nodes[0].add_expected_peer(slot+1, slot, ('127.0.0.1', roster[slot]['port']))
            nodes[slot].peers[1].slot = 0
            nodes[slot].peers[1].strict = True
        report['udp_addresses'] = roster
        released, compared, last_progress = False, False, time.monotonic()
        start, next_log, previous = time.monotonic(), 0, None
        while time.monotonic()-start < seconds and not (root/'STOP').exists():
            for node in nodes:
                node.sock.tick()
                node.pump()
            if not released and all(n.started and min(n.published.values()) >= 1 for n in nodes):
                for core in cores:
                    core.release()
                released = True
                emit({'ready': True, 'message': 'Entradas programadas para los cuatro puestos.' if scripted else
                      'P1 recibe tu mando; P2-P4 confirman personaje y quedan neutrales.'})
            frames = [c.get('frame') for c in cores]
            if any(c.get('abort') for c in cores):
                raise ValueError('Un emulador abortó el adaptador.')
            if any(n.desync is not None for n in nodes):
                raise ValueError('Difieren las entradas recibidas por los nodos.')
            if frames != previous:
                last_progress, previous = time.monotonic(), frames
            if point_index < len(points) and frames == [checkpoint]*4 and all(c.get('status') == 2 for c in cores):
                memory = [snapshot(c, s['state_dir'], root/f'frame-{checkpoint}-P{i+1}.p2s')
                          for i,(c,s) in enumerate(zip(cores,sessions))]
                report['ram_at_checkpoint'] = {f'P{i+1}':ram_comparison(memory[0],memory[i]) for i in (1,2,3)}
                report.setdefault('comparisons', {})[str(checkpoint)] = report['ram_at_checkpoint']
                report['checkpoint_reached'] = True
                save()
                point_index += 1
                next_checkpoint = points[point_index] if point_index < len(points) else 0xffffffff
                for wrapper in wrappers:
                    wrapper.extend(next_checkpoint)
                compared = point_index == len(points)
                emit({'checkpoint_reached': checkpoint, 'gameplay_sync_certified': False})
                checkpoint = next_checkpoint
            if time.monotonic()-last_progress > 30:
                report['stalled'] = [json.loads(stalled_details(n,c,f)) for n,c,f in zip(nodes,cores,frames)]
                for i, (core, session) in enumerate(zip(cores, sessions)):
                    report['stalled'][i]['pcsx2_status'] = core.pine.status()
                    try:
                        snapshot(core, session['state_dir'], root/f'stalled-P{i+1}.p2s')
                    except Exception as error:
                        report['stalled'][i]['snapshot_error'] = str(error)
                raise ValueError('Sin avance durante 30 segundos; ver report.json.')
            if time.monotonic() >= next_log:
                report.update(frames=frames,input_hashes_checked=nodes[0].checked,
                    physical_non_neutral_frames=None if scripted else wrappers[0].non_neutral,
                    p1_non_neutral_frames=wrappers[0].non_neutral,
                    started=[n.started for n in nodes],routes=[n.sock.route_stats() for n in nodes])
                save()
                emit({'frames':frames,'input_hashes_checked':nodes[0].checked,
                      'p1_non_neutral_frames':wrappers[0].non_neutral})
                next_log=time.monotonic()+3
            time.sleep(.002)
        report['completed'] = released and compared
        report['stopped_by_user'] = (root/'STOP').exists()
    except BaseException as error:
        report['error'] = str(error)
        emit({'error': str(error)})
        raise
    finally:
        for core in cores:
            try:
                core.stop()
            except Exception:
                pass
        for node in nodes:
            try:
                node.close()
            except Exception:
                node.sock.close()
        for p in connections:
            p.close()
        for process in processes:
            # Flatpak's launcher can exit before its emulator descendants.
            # Reap the entire group even if Popen already reports an exit.
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        report['ended_utc'] = datetime.now(timezone.utc).isoformat()
        save()
        emit({'report':str(root/'report.json'),'completed':report['completed']})
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=180)
    parser.add_argument('--output',type=Path,default=Path('build/digimon')/('local-4p-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')))
    parser.add_argument('--scripted',action='store_true',help='Usar botones programados también para P1.')
    parser.add_argument('--checkpoints',type=int,nargs='+',help='Fotogramas exactos donde comparar las cuatro instancias.')
    args=parser.parse_args()
    if not 15<=args.seconds<=1800:
        parser.error('La duración debe estar entre 15 y 1800 segundos.')
    run(args.output,args.seconds,scripted=args.scripted,checkpoints=args.checkpoints)
