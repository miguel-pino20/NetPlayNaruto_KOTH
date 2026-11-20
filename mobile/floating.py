"""Small native, draggable host control; no full-screen touch interception."""
from pathlib import Path
import threading
import time


if __package__:
    from .mobile_locale import tr
else:
    from mobile_locale import tr


def create_overlay(config):
    if not config.get('overlay', False):
        return None
    from jnius import autoclass, PythonJavaClass, java_method
    service = autoclass('org.kivy.android.PythonService').mService
    Settings = autoclass('android.provider.Settings')
    if not Settings.canDrawOverlays(service):
        raise RuntimeError(tr('Falta permitir el control flotante en los ajustes de Android.'))
    Context = autoclass('android.content.Context')
    manager = service.getSystemService(Context.WINDOW_SERVICE)
    Params = autoclass('android.view.WindowManager$LayoutParams')
    TextView = autoclass('android.widget.TextView')
    Color = autoclass('android.graphics.Color')
    String = autoclass('java.lang.String')
    Handler = autoclass('android.os.Handler')
    Looper = autoclass('android.os.Looper')
    handler = Handler(Looper.getMainLooper())
    done = threading.Event()
    state = {}
    position = Path(config['directory']) / 'overlay-position.json'
    player = 'P2' if config.get('role') == 'guest' else 'P1'

    class Touch(PythonJavaClass):
        __javainterfaces__ = ['android/view/View$OnTouchListener']
        __javacontext__ = 'app'

        @java_method('(Landroid/view/View;Landroid/view/MotionEvent;)Z')
        def onTouch(self, view, event):
            action = event.getActionMasked()
            params = state['params']
            if action == 0:
                self.down = time.monotonic()
                self.x, self.y = event.getRawX(), event.getRawY()
                self.start_x, self.start_y = params.x, params.y
                self.moved = False
            elif action == 2 and hasattr(self, 'down'):
                dx, dy = event.getRawX() - self.x, event.getRawY() - self.y
                if abs(dx) + abs(dy) > state['density'] * 8:
                    self.moved = True
                if self.moved:
                    metrics = service.getResources().getDisplayMetrics()
                    params.x = int(max(0, min(metrics.widthPixels - state['width'], self.start_x + dx)))
                    params.y = int(max(0, min(metrics.heightPixels - state['height'], self.start_y + dy)))
                    manager.updateViewLayout(view, params)
            elif action == 1 and hasattr(self, 'down'):
                if self.moved:
                    from appdata import write_json
                    write_json(position, {'x': params.x, 'y': params.y}, private=True)
                elif time.monotonic() - self.down >= 1:
                    Path(config['stop_file']).touch()
                    state['view'].setText(String('Deteniendo ' + player + '…'))
            return True

    class Add(PythonJavaClass):
        __javainterfaces__ = ['java/lang/Runnable']
        __javacontext__ = 'app'

        @java_method('()V')
        def run(self):
            try:
                from backend import load_preferences
                metrics = service.getResources().getDisplayMetrics()
                density = metrics.density
                width, height = int(128 * density), int(30 * density)
                # Non-focusable: touching/dragging the pill does not pause ARMSX2.
                params = Params(width, height, 2038, 8 | 32, -3)
                params.gravity = 48 | 3
                saved = load_preferences(position)
                params.x = int(max(0, min(metrics.widthPixels - width,
                                         saved.get('x', (metrics.widthPixels - width) // 2))))
                params.y = int(max(0, min(metrics.heightPixels - height, saved.get('y', 10 * density))))
                params.alpha = 0.75
                text = TextView(service)
                text.setText(String(player + ' · mantener: parar'))
                text.setTextSize(11.0)
                text.setTextColor(Color.WHITE)
                text.setBackgroundColor(Color.parseColor('#CC10243B'))
                text.setGravity(17)
                text.setContentDescription(String(tr('{player}. Arrastra para mover. Mantén pulsado un segundo y suelta para detener.', player=player)))
                touch = Touch()
                text.setOnTouchListener(touch)
                state.update(view=text, params=params, density=density, width=width, height=height, touch=touch)
                manager.addView(text, params)
            except BaseException as error:
                state['error'] = str(error)
            finally:
                done.set()

    add = Add()
    handler.post(add)
    if not done.wait(5) or 'error' in state:
        raise RuntimeError(tr('No se pudo mostrar el control flotante: {error}', error=state.get('error') or tr('sin respuesta de Android')))

    class Remove(PythonJavaClass):
        __javainterfaces__ = ['java/lang/Runnable']
        __javacontext__ = 'app'
        @java_method('()V')
        def run(self):
            try:
                manager.removeView(state['view'])
            except Exception:
                pass

    class Overlay:
        # Keep JNI proxies alive for the lifetime of the service.
        refs = (state, add, handler)
        def close(self):
            self.remove = Remove()
            handler.post(self.remove)
    return Overlay()
