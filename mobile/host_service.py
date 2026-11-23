"""Foreground host service entry point, intentionally independent of Kivy."""
import json
import os
from pathlib import Path
import sys
import time

from backend import configure_storage
from mobile_locale import set_language, tr


def show_notification(transport='direct', role='host'):
    # p4a's default channel has IMPORTANCE_NONE. Use a visible, ongoing channel
    # for this user-started network session instead of an invisible notification.
    from jnius import autoclass
    service = autoclass('org.kivy.android.PythonService').mService
    Context = autoclass('android.content.Context')
    Channel = autoclass('android.app.NotificationChannel')
    Manager = autoclass('android.app.NotificationManager')
    manager = service.getSystemService(Context.NOTIFICATION_SERVICE)
    channel_id = 'un5_netplay_host'
    manager.createNotificationChannel(Channel(channel_id, tr('Partida Naruto Netplay'), Manager.IMPORTANCE_LOW))
    intent = service.getPackageManager().getLaunchIntentForPackage(service.getPackageName())
    PendingIntent = autoclass('android.app.PendingIntent')
    pending = PendingIntent.getActivity(service, 0, intent,
                                       PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)
    Builder = autoclass('android.app.Notification$Builder')
    notification = (Builder(service, channel_id).setSmallIcon(service.getApplicationInfo().icon)
                    .setContentTitle('Naruto Netplay · ' + ({'host': 'Host P1', 'guest': tr('Cliente P2'), 'koth': 'KOTH'}[role]))
                    .setContentText(tr('Coordinando turnos con Django') if role == 'koth' else tr('Sala UN5 · esperando jugador 2') if transport == 'server' else tr('Esperando jugador 2 · UDP 47400'))
                    .setContentIntent(pending).setOngoing(True).build())
    service.startForeground(1, notification)


def main():
    import fcntl
    config = json.loads(os.environ['PYTHON_SERVICE_ARGUMENT'])
    configure_storage(config['directory'])
    set_language(config.get('language'))
    from appdata import write_json
    from host import run_host
    status_path = Path(config['directory']) / 'host-status.json'
    lock = (Path(config['directory']) / 'host.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    coordination_error = ''

    def report(state, message):
        room_id = config.get('room_id', '') if config.get('role') == 'guest' else ''
        if config.get('transport') == 'server' and config.get('role', 'host') == 'host':
            try:
                room_id = json.loads((Path(config['directory']) / 'host-room.json').read_text()).get('room_id', '')
            except (OSError, ValueError):
                pass
        if room_id and state in ('waiting', 'playing'):
            message = tr('Sala UN5: {room}', room=room_id) + '\n' + str(message)
        write_json(status_path, {'phase': state, 'message': str(message)[-1800:],
                                 'room_id': room_id, 'transport': config.get('transport', 'direct'),
                                 'role': config.get('role', 'host'),
                                 'tournament': bool(config.get('fixture')),
                                 'time': time.time(), 'pid': os.getpid()}, private=True)

    class StatusOutput:
        def __init__(self, output):
            self.output, self.pending = output, ''
        def write(self, text):
            nonlocal coordination_error
            self.output.write(text)
            self.pending = (self.pending + text)[-4000:]
            while '\n' in self.pending:
                line, self.pending = self.pending.split('\n', 1)
                if config.get('role') == 'koth':
                    continue
                if line.startswith('ZeroTier:'):
                    report('waiting', line)
                elif line.startswith('No se pudo coordinar el cruce'):
                    coordination_error = line
                elif line.startswith('host: waiting'):
                    report('waiting', 'HOST P1 · UDP 47400\n' + line)
                elif line.startswith('host: room '):
                    report('waiting', tr('HOST P1 · Sala publicada en el servidor UN5. Esperando jugador 2.'))
                elif line.startswith('guest:'):
                    report('waiting', 'CLIENTE P2 · ' + line)
                elif line.startswith('waiting for the other PC'):
                    report('waiting', tr('CLIENTE P2 · Conectando a P1. Mantén ARMSX2 visible y reanudado.')
                           if config.get('role') == 'guest' else
                           tr('HOST P1 · Esperando jugador 2. Mantén ARMSX2 visible y reanudado.')
                           if config.get('transport') == 'server' else
                           tr('HOST P1 · Esperando jugador 2 en UDP 47400. Mantén ARMSX2 visible y reanudado.'))
                elif line.startswith('frame='):
                    report('playing', line)
            return len(text)
        def flush(self):
            self.output.flush()

    output = sys.stdout
    sys.stdout = StatusOutput(output)
    overlay = None
    try:
        show_notification(config.get('transport', 'direct'), config.get('role', 'host'))
        from floating import create_overlay
        overlay = create_overlay(config)
        if config.get('role') == 'koth':
            from koth import run_koth
            code = run_koth(config, report)
        else:
            report('starting', tr('Host P1 iniciando. Vuelve a ARMSX2 y pulsa Reanudar.'))
            code = run_host(config, report)
        report('stopped' if code == 0 else 'error',
               coordination_error or tr('Sesión finalizada (código {code}).', code=code))
    except InterruptedError as error:
        report('stopped', str(error))
    except BaseException as error:
        report('error', str(error))
    finally:
        if overlay is not None:
            overlay.close()
        sys.stdout = output
        lock.close()


if __name__ == '__main__':
    main()
