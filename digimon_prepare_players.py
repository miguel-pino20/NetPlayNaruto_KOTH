"""Prepare character-selection participants using one physical controller.

This is a state-creator action, not a game/transport test. Back up the current
screen to a previously unused slot, then issue one brief X pulse with DualShock 2 pressure to each
additional virtual pad. P1 receives neutral input throughout. No ISO changes.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
import zipfile

from digimon_core import DigimonCore
from don_setup import latest_state_directory
from pine import Pine
from wire import IDLE_PAD


def prepare_players(adapter, state_dir, players=4, output=None, button='cross', pine_slot=28011, first_player=2):
    if players not in (2, 3, 4) or button not in ('start', 'cross'):
        raise ValueError('Selecciona 2–4 jugadores y START o CROSS.')
    if type(first_player) is not int or not 2 <= first_player <= players:
        raise ValueError('El primer puesto por incorporar debe estar entre P2 y el total seleccionado.')
    directory = Path(state_dir)
    if not directory.is_dir():
        raise ValueError('No se encontró la carpeta de estados de PCSX2.')
    root = Path(output or Path('build/digimon/preparations')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    root.mkdir(parents=True, exist_ok=False)
    pine = Pine(pine_slot, timeout=3)
    core, armed = None, False
    report = {'utc': datetime.now(timezone.utc).isoformat(), 'action': 'join_players',
              'players': players, 'first_player': first_player, 'button': button,
              'p1_input': 'neutral', 'combat_start_requested': False}
    try:
        pine.connect()
        metadata = json.loads(Path(adapter).read_text())
        core = DigimonCore(pine, metadata)
        if pine.status() != 0 or core.get('active'):
            raise ValueError('Reanuda el juego y termina cualquier sesión de netplay antes de preparar los puestos.')
        slot = next((s for s in range(9, -1, -1) if not any(directory.glob(f'*.{s:02}.p2s'))), None)
        if slot is None:
            raise ValueError('No hay una ranura libre; no se sobrescriben estados.')
        target = directory/f"{metadata['source_serial']} ({pine.game_crc()}).{slot:02}.p2s"
        pine.save_state(slot)
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            try:
                with zipfile.ZipFile(target) as archive:
                    if archive.getinfo('eeMemory.bin').file_size != 32*1024*1024:
                        raise ValueError('RAM incompleta en el respaldo.')
                shutil.copyfile(target, root/'before-join.p2s')
                break
            except (FileNotFoundError, zipfile.BadZipFile, KeyError):
                time.sleep(.1)
        else:
            raise ValueError('No se creó el respaldo; no se enviaron pulsaciones.')
        report.update(backup_slot=slot, backup_path=str(target), local_backup=str(root/'before-join.p2s'))
        armed = True
        core.arm(4)  # Keep all four physical sockets alive even with 2–3 humans.
        frames = 84
        pressed = bytearray(IDLE_PAD)
        if button == 'start':
            pressed[2] &= ~0x08
        else:
            pressed[3] &= ~0x40
            # Digimon's DualShock 2 decoder uses pressure byte 14 for X in
            # mode 0x79. Changing only its active-low digital bit is ignored.
            pressed[14] = 255
        for slot in range(4):
            pulse = 10+(slot+1-first_player)*20
            core.publish(slot, {f: (bytes(pressed) if first_player <= slot+1 <= players and pulse <= f < pulse+2 else IDLE_PAD, 0)
                                for f in range(frames)})
        core.release()
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            if core.get('abort'):
                raise ValueError('El adaptador abortó; comprueba que el mando físico 1A siga conectado.')
            frame = core.get('frame')
            if frame >= frames:
                report['frames_applied'] = frame
                report['pulses_sent_to'] = list(range(first_player, players+1))
                report['visual_confirmation_required'] = True
                break
            time.sleep(.01)
        else:
            raise ValueError('No se completaron las pulsaciones de preparación a tiempo.')
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if armed and core is not None:
            try:
                core.stop()
                report['physical_controls_restored'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
        pine.close()
        (root/'join-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter', type=Path, default=Path('build/digimon/adapter-v1/adapter.json'))
    parser.add_argument('--state-dir', type=Path, default=Path(latest_state_directory()))
    parser.add_argument('--players', type=int, choices=(2, 3, 4), default=4)
    parser.add_argument('--first-player', type=int, default=2, help='Primer puesto OPEN por incorporar; deja los anteriores neutrales.')
    parser.add_argument('--pine-slot', type=int, default=28011)
    parser.add_argument('--button', choices=('start', 'cross'), default='cross')
    parser.add_argument('--character-select-confirmed', action='store_true', required=True,
                        help='Confirma que el juego está en selección de personajes con P1 dentro y otros puestos OPEN.')
    args = parser.parse_args()
    print(json.dumps(prepare_players(args.adapter, args.state_dir, args.players,
                                    button=args.button, pine_slot=args.pine_slot,
                                    first_player=args.first_player), indent=2))
