"""Prepare/start a separate PCSX2 instance for the D.O.N loopback experiment.

Copies settings and an unused local save card into build/, uses PINE 28012,
and points only the BIOS folder at existing read-only game setup resources.
"""
import argparse
import configparser
import json
import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path


def prepare(adapter, source_data, target, card, pine_slot=28012):
    if type(pine_slot) is not int or not 1 <= pine_slot <= 65535:
        raise ValueError('Ranura PINE inválida.')
    adapter, source_data, target, card = map(Path, (adapter, source_data, target, card))
    metadata = json.loads(adapter.read_text())
    if metadata.get('experimental') is not True or metadata.get('adapter') != 'don-experimental-input-v1':
        raise ValueError('Este comando solo admite la compilación experimental local de D.O.N.')
    for path in (source_data/'inis/PCSX2.ini', Path(metadata['boot_path']), Path(metadata['disc_path']), card):
        if not path.is_file():
            raise ValueError(f'Falta el archivo {path}')
    config = configparser.RawConfigParser(strict=False)
    config.optionxform = str
    config.read(source_data/'inis/PCSX2.ini')
    bios = Path(config.get('Folders', 'Bios', fallback='bios'))
    if not bios.is_absolute():
        bios = source_data/bios
    if not (bios/config.get('Filenames', 'BIOS')).is_file():
        raise ValueError('No se encontró la BIOS seleccionada en el emulador habitual.')
    target.mkdir(parents=True, exist_ok=False)
    # PCSX2 2.8.2 appends its application name to the -datapath base.
    data_root = target/'PCSX2'
    for section, values in {
        'UI': {'SetupWizardIncomplete': 'false', 'PauseOnFocusLoss': 'false', 'StartFullscreen': 'false'},
        'EmuCore': {'EnablePINE': 'true', 'PINESlot': str(pine_slot), 'SaveStateOnShutdown': 'false',
                    'EnablePatches': 'false', 'EnableCheats': 'false', 'McdFolderAutoManage': 'false'},
        'Achievements': {'Enabled': 'false'},
        'MemoryCards': {'Slot1_Enable': 'true', 'Slot1_Filename': 'DON-Latino-test.ps2', 'Slot2_Enable': 'false'},
        'Pad': {'MultitapPort1': 'true', 'MultitapPort2': 'false'},
    }.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in values.items():
            config.set(section, key, value)
    # No writable folder in this instance should point into the usual data tree.
    for key in list(config['Folders']):
        config.set('Folders', key, str(bios.resolve()) if key == 'Bios' else str(data_root.resolve()/key.lower()))
    config.set('Folders', 'MemoryCards', str(data_root.resolve()/'memcards'))
    (data_root/'inis').mkdir(parents=True)
    (data_root/'memcards').mkdir()
    with (data_root/'inis/PCSX2.ini').open('w') as output:
        config.write(output, space_around_delimiters=True)
    shutil.copyfile(card, data_root/'memcards/DON-Latino-test.ps2')
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    command = ['flatpak', 'run', f'--filesystem={adapter.resolve().parent}',
               f'--filesystem={target.resolve()}', f'--filesystem={Path(metadata["disc_path"]).resolve()}:ro',
               f'--filesystem={bios.resolve()}:ro',
               f'--env=XDG_RUNTIME_DIR={runtime}/app/net.pcsx2.PCSX2']
    display = os.environ.get('WAYLAND_DISPLAY')
    if display and not display.startswith('/'):
        command.append(f'--env=WAYLAND_DISPLAY={runtime}/{display}')
    command += ['net.pcsx2.PCSX2', '-batch', '-nofullscreen', '-datapath', str(target.resolve()),
                '-elf', metadata['boot_path'], '-fastboot', '--', metadata['disc_path']]
    session = {'command': command, 'data_path': str(target.resolve()),
               'adapter': str(adapter.resolve()), 'pine_slot': pine_slot, 'pid': None}
    (target/'session.json').write_text(json.dumps(session, indent=2)+'\n')
    return session


def start(session_path, foreground=False):
    session_path = Path(session_path)
    session = json.loads(session_path.read_text())
    if session.get('pid'):
        raise ValueError('Esta sesión ya fue iniciada.')
    with (session_path.parent/'startup.log').open('xb') as log:
        process = subprocess.Popen(session['command'], stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    session['pid'] = process.pid
    session_path.write_text(json.dumps(session, indent=2)+'\n')
    if foreground:
        code = process.wait()
        print(f'La instancia de prueba terminó con código {code}.')
    return session


def stop(session_path):
    session = json.loads(Path(session_path).read_text())
    pid = session.get('pid')
    if not pid:
        return
    proc = Path('/proc')/str(pid)
    if not proc.exists():
        return
    command = (proc/'cmdline').read_bytes()
    if session['data_path'].encode() not in command or os.getpgid(pid) != pid:
        raise ValueError('El proceso no coincide con esta instancia de prueba; no se cierra.')
    os.killpg(pid, signal.SIGTERM)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--adapter', type=Path, default=Path('build/don/adapter.json'))
    p.add_argument('--source-data', type=Path, default=Path.home()/'.var/app/net.pcsx2.PCSX2/config/PCSX2')
    p.add_argument('--target', type=Path, default=Path('build/don/pcsx2-test'))
    p.add_argument('--card', type=Path, default=Path('saves/DON-Latino-desbloqueado.ps2'))
    p.add_argument('--pine-slot', type=int, default=28012)
    for name in ('start', 'stop'):
        p = sub.add_parser(name)
        p.add_argument('session', type=Path)
        if name == 'start':
            p.add_argument('--foreground', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            result = prepare(args.adapter, args.source_data, args.target, args.card, args.pine_slot)
            print(shlex.join(result['command']))
        elif args.action == 'start':
            print(json.dumps(start(args.session, args.foreground), indent=2))
        else:
            stop(args.session)
    except (ValueError, OSError, configparser.Error) as error:
        parser.exit(1, str(error)+'\n')
