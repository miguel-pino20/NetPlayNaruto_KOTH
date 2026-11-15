"""Naruto Netplay mobile foundation (Kivy/Python)."""
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault('KIVY_NO_ARGS', '1')
# On desktop use the actual shared sources; packaging copies an explicit allowlist.
ROOT = Path(__file__).resolve().parent.parent
if (ROOT / 'pine.py').is_file():
    sys.path.insert(0, str(ROOT))

from kivy.config import Config
Config.set('graphics', 'maxfps', '30')
Config.set('kivy', 'exit_on_escape', '0')
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from release_info import VERSION
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.utils import platform
from backend import configure_storage, https_url, validate_address, pine_diagnostics, load_preferences, make_account


class MobileApp(App):
    title = 'Naruto Netplay · ' + VERSION
    # Elementos Directo / ZeroTier
    def build(self):
        configure_storage(self.user_data_dir)
        if platform == 'android':
            # Python's desktop browser discovery does not launch Android intents.
            import webbrowser
            from jnius import autoclass
            class AndroidBrowser:
                def open(self, url, new=0, autoraise=True):
                    from urllib.parse import urlsplit
                    if urlsplit(url).scheme != 'https':
                        raise ValueError('Discord debe abrirse mediante HTTPS.')
                    Intent = autoclass('android.content.Intent')
                    Uri = autoclass('android.net.Uri')
                    activity = autoclass('org.kivy.android.PythonActivity').mActivity
                    activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                    return True
            webbrowser.register('android', None, AndroidBrowser(), preferred=True)
        from appdata import DATA_DIR
        self.prefs_path = DATA_DIR / 'mobile.json'
        self.prefs = load_preferences(self.prefs_path)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mobile-api')
        self.busy = False
        self.closed = False
        self.auth_timer = None
        self.host_timer = None
        self.account = make_account('https://un5netplay.duckdns.org')
        self.inputs = {}
        self.host_ip = None
        root = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(8))
        brand = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        brand.add_widget(Image(source=str(Path(__file__).with_name('un5-netplay.png')),
                               size_hint_x=None, width=dp(52)))
        brand.add_widget(self.label('NARUTO NETPLAY', 52, 20))
        root.add_widget(brand)
        root.add_widget(self.label('Base Android · PINE / ZeroTier / KOTH', 26))
        tabs = TabbedPanel(do_default_tab=False, tab_width=dp(72))
        self.connection = self.page(tabs, 'Conexión')
        self.available_release = None
        self.label_in(self.connection, 'Versión ' + VERSION, 16, 36)
        self.update_label = self.label_in(self.connection, 'Actualizaciones de GitHub', 14, 70)
        self.button(self.connection, 'Buscar actualizaciones', self.check_updates)
        self.update_download_button = self.button(self.connection, 'Descargar actualización', self.download_update)
        self.update_download_button.disabled = True
        self.update_install_button = self.button(self.connection, 'Instalar actualización', self.install_update)
        self.update_install_button.disabled = True
        self.label_in(self.connection, 'ARMSX2 local', 20)
        self.field(self.connection, 'pine_slot', 'Puerto PINE', '28011', numeric=True)
        self.button(self.connection, 'Probar PINE (solo lectura)', self.test_pine)
        self.label_in(self.connection, 'Estado compartido para ARMSX2', 17, 42)
        self.export_game = Spinner(text=self.prefs.get('game', 'un6'), values=('un5', 'un6'),
                                   size_hint_y=None, height=dp(48))
        self.connection.add_widget(self.export_game)
        self.button(self.connection, 'Descargar estado en Descargas', self.export_state)
        self.label_in(self.connection, 'Se guarda en Descargas/NarutoNetplay. '
                      'Debes pasarlo a ARMSX2 por tu cuenta.', 14, 80)
        self.label_in(self.connection, 'ZeroTier')
        self.field(self.connection, 'zt_address', 'Tu IPv4 de ZeroTier', '')
        self.button(self.connection, 'Guardar configuración', self.save_connection)
        self.label_in(self.connection, 'Conecta y autoriza la red desde ZeroTier.\nEl host experimental se inicia en la pestaña Host P1.', 14, 92)
        host = self.page(tabs, 'Host P1')
        self.game = Spinner(text=self.prefs.get('game', 'un6'), values=('un5', 'un6'),
                            size_hint_y=None, height=dp(48))
        host.add_widget(self.game)
        self.host_transport = Spinner(text='Directo / ZeroTier' if self.prefs.get('transport') == 'direct' else 'Servidor UN5',
                                 values=('Servidor UN5', 'Directo / ZeroTier'), size_hint_y=None, height=dp(48))
        host.add_widget(self.host_transport)
        row = BoxLayout(size_hint_y=None, height=dp(42))
        row.add_widget(self.label('Control flotante movible', 42, 14))
        self.overlay = Switch(active=bool(self.prefs.get('overlay', True)), size_hint_x=0.3)
        row.add_widget(self.overlay)
        host.add_widget(row)
        self.button(host, 'Crear partida como jugador 1', self.start_host)
        self.button(host, 'Detener partida', self.stop_host)
        self.button(host, 'Volver a ARMSX2', self.open_emulator)
        self.host_status = self.label_in(host, 'Host detenido.', 14, 160)
        self.label_in(host, 'El slot 1 de ARMSX2 debe contener el estado compartido preparado.\n'
                      'La app descarga una copia privada, pero no puede instalarla en ARMSX2 automáticamente.\n'
                      'Servidor UN5: la sala aparece en PC. Directo/ZeroTier: P2 conecta a tu IP, UDP 47400.', 14, 160)
        client = self.page(tabs, 'Cliente P2')
        self.client_game = Spinner(text=self.prefs.get('client_game', self.game.text), values=('un5', 'un6'),
                                   size_hint_y=None, height=dp(48))
        client.add_widget(self.client_game)
        self.client_transport = Spinner(
            text='Directo / ZeroTier' if self.prefs.get('client_transport') == 'direct' else 'Servidor UN5',
            values=('Servidor UN5', 'Directo / ZeroTier'), size_hint_y=None, height=dp(48))
        client.add_widget(self.client_transport)
        self.transport_container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10))
        self.transport_container.bind(minimum_height=self.transport_container.setter('height'))
        client.add_widget(self.transport_container)
        self.direct_box = BoxLayout(orientation='vertical', spacing=dp(10), size_hint_y=None)
        self.direct_box.bind(minimum_height=self.direct_box.setter('height'))
        self.label_in(self.direct_box, 'IPv4 del host P1 · puerto 47400', 14, 32)
        self.host_ip = TextInput(text=self.prefs.get('guest_host', ''), hint_text='IP del host',
                                 multiline=False, size_hint_y=None, height=dp(48))
        self.direct_box.add_widget(self.host_ip)
        self.server_box = BoxLayout(orientation='vertical', spacing=dp(10), size_hint_y=None)
        self.server_box.bind(minimum_height=self.server_box.setter('height'))
        self.button(self.server_box, 'Actualizar salas UN5', self.refresh_rooms)
        self.room_choices = {}
        self.rooms_box = BoxLayout(orientation='vertical', spacing=dp(6), size_hint_y=None)
        self.rooms_box.bind(minimum_height=self.rooms_box.setter('height'))
        self.label_in(self.rooms_box, 'Pulsa Actualizar salas para buscar jugadores.', 14, 50)
        self.server_box.add_widget(self.rooms_box)
        self.room_input = TextInput(text=self.prefs.get('client_room', ''), hint_text='Código de sala',
                                    multiline=False, size_hint_y=None, height=dp(48))
        self.server_box.add_widget(self.room_input)
        self.client_transport.bind(text=self.on_transport_change)
        self.on_transport_change(self.client_transport, self.client_transport.text)
        self.button(client, 'Conectar como jugador 2', self.start_client)
        self.button(client, 'Desconectar', self.stop_host)
        self.button(client, 'Volver a ARMSX2', self.open_emulator)
        self.client_status = self.label_in(client, 'Sin conexión.', 14, 150)
        self.label_in(client, 'Usa tus controles locales del mando 1: netplay los asigna al jugador 2. '
                      'Ambos puertos virtuales se preparan como DualShock 2.', 14, 100)
        client.bind(on_release=lambda *_: self.refresh_rooms() if self.client_transport.text == 'Servidor UN5' and not self.busy else None)

        koth = self.page(tabs, 'KOTH')
        self.field(koth, 'koth_url', 'Servidor KOTH (HTTPS)', 'https://narutimateonline.servegame.com')
        self.button(koth, 'Consultar eventos', self.list_events)
        self.events = self.label_in(koth, 'Consulta manual, sin sondeo continuo.\nInscripción y partidas pendientes de integración.', 14, 240)
        account = self.page(tabs, 'Discord')
        self.account_label = self.label_in(account, 'Sin sesión verificada', 17, 70)
        self.login_button = self.button(account, 'Iniciar sesión con Discord', self.login)
        self.button(account, 'Cancelar login', self.cancel_login)
        self.button(account, 'Cerrar sesión', self.logout)
        self.label_in(account, 'El login abre el navegador y usa el servidor existente.\nLa sesión se guarda en los datos privados de esta app.\nNunca se incluye el secreto de Discord en el APK.', 14, 125)
        root.add_widget(tabs)
        self.status = self.label('Listo. Activa PINE en ARMSX2 antes de probar.', 140)
        root.add_widget(self.status)
        if self.account.session:
            self.account.acct_restore()
            self.watch_account()
        self.watch_host()
        if platform == 'android':
            Clock.schedule_once(lambda _: self.check_updates(automatic=True), 2)
        return root

    def label(self, text, height=48, size=14):
        widget = Label(text=text, size_hint_y=None, height=dp(height), font_size=dp(size),
                       halign='left', valign='middle')
        widget.bind(size=lambda instance, value: setattr(instance, 'text_size', (value[0], value[1])))
        return widget

    def label_in(self, parent, text, size=16, height=48):
        widget = self.label(text, height, size)
        parent.add_widget(widget)
        return widget

    def page(self, tabs, title):
        tab = TabbedPanelItem(text=title)
        scroll = ScrollView()
        content = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10), padding=dp(8))
        content.bind(minimum_height=content.setter('height'))
        scroll.add_widget(content)
        tab.add_widget(scroll)
        tabs.add_widget(tab)
        return content

    def field(self, parent, key, title, default, numeric=False):
        self.label_in(parent, title, 14, 28)
        field = TextInput(text=str(self.prefs.get(key, default)), multiline=False,
                          size_hint_y=None, height=dp(48), font_size=dp(16))
        if numeric:
            field.input_filter = 'int'
        self.inputs[key] = field
        parent.add_widget(field)

    def button(self, parent, text, action):
        button = Button(text=text, size_hint_y=None, height=dp(48), font_size=dp(15))
        button.bind(on_release=lambda *_: action())
        parent.add_widget(button)
        return button

    def say(self, message):
        if not self.closed:
            self.status.text = str(message)[:1400]

    def run_job(self, job, success):
        if self.busy:
            self.say('Espera a que termine la consulta actual.')
            return
        self.busy = True
        self.say('Consultando…')
        future = self.worker.submit(job)
        def finish(_):
            self.busy = False
            if self.closed:
                return
            try:
                success(future.result())
            except Exception as error:
                self.say(str(error))
        future.add_done_callback(lambda _: Clock.schedule_once(finish))

    def persist(self):
        from appdata import write_json
        self.prefs = {key: field.text.strip() for key, field in self.inputs.items()}
        self.prefs['game'] = self.game.text
        self.prefs['overlay'] = self.overlay.active
        self.prefs['transport'] = 'server' if self.host_transport.text == 'Servidor UN5' else 'direct'
        self.prefs['client_transport'] = 'server' if self.client_transport.text == 'Servidor UN5' else 'direct'
        self.prefs['client_game'] = self.client_game.text
        self.prefs['guest_host'] = self.host_ip.text.strip()
        self.prefs['client_room'] = self.room_input.text.strip()
        write_json(self.prefs_path, self.prefs, private=True)

    def save_connection(self):
        try:
            slot = int(self.inputs['pine_slot'].text)
            if not 1 <= slot <= 65535:
                raise ValueError('Puerto PINE inválido.')
            if self.inputs['zt_address'].text.strip():
                validate_address(self.inputs['zt_address'].text)
            https_url(self.inputs['koth_url'].text)
            self.persist()
            self.say('Configuración guardada. La conectividad ZeroTier aún debe probarse en una partida.')
        except Exception as error:
            self.say(str(error))

    def check_updates(self, automatic=False):
        if self.busy:
            if automatic and not self.closed:
                Clock.schedule_once(lambda _: self.check_updates(automatic=True), 10)
            return
        from updater import find_update
        def check():
            try:
                return find_update('android'), ''
            except Exception as error:
                return None, str(error)
        self.update_label.text = 'Buscando actualizaciones…'
        def show(result):
            release, error = result
            if error:
                self.update_label.text = 'No se pudo comprobar: ' + error
                return
            self.say('Consulta de actualizaciones completada.')
            self.available_release = release
            self.update_download_button.disabled = release is None
            self.update_label.text = ('Disponible: ' + release.version if release else
                                      'No hay una actualización posterior a ' + VERSION)
            if release and automatic:
                content = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))
                content.add_widget(self.label('Nueva versión ' + release.version + '. ¿Descargar APK?', 70))
                popup = Popup(title='Actualización disponible', content=content,
                              size_hint=(0.92, None), height=dp(240))
                def download():
                    popup.dismiss()
                    self.download_update()
                self.button(content, 'Descargar', download)
                self.button(content, 'Más tarde', popup.dismiss)
                popup.open()
        self.run_job(check, show)

    def update_allowed(self):
        from host import ACTIVE
        state = load_preferences(Path(self.user_data_dir) / 'host-status.json')
        if state.get('phase') in ACTIVE:
            self.say('Detén la partida antes de descargar o instalar una actualización.')
            return False
        return True

    def download_update(self):
        if not self.available_release or not self.update_allowed():
            return
        from updates import download_update
        release = self.available_release
        self.update_label.text = 'Descargando ' + release.version + ' y verificando SHA256…'
        def fetch():
            try:
                return download_update(self.user_data_dir, release), ''
            except Exception as error:
                return None, str(error)
        def ready(result):
            _, error = result
            if error:
                self.update_label.text = 'No se pudo descargar: ' + error
                self.say(error)
                self.update_install_button.disabled = True
                return
            self.update_label.text = 'APK ' + release.version + ' verificado. Pulsa Instalar actualización.'
            self.update_install_button.disabled = False
        self.run_job(fetch, ready)

    def install_update(self):
        if platform != 'android' or not self.update_allowed():
            return
        from updates import install_update
        try:
            self.say(install_update(self.user_data_dir))
        except Exception as error:
            self.say(str(error))

    def export_state(self):
        if platform != 'android':
            self.say('Guardar en Descargas está disponible en Android 10 o posterior.')
            return
        from downloads import download_state
        game = self.export_game.text
        self.say('Descargando y verificando estado ' + game.upper() + '…')
        self.run_job(lambda: download_state(self.user_data_dir, game), self.say)

    def test_pine(self):
        slot = self.inputs['pine_slot'].text
        self.run_job(lambda: pine_diagnostics(slot, android=platform == 'android'), self.say)

    def list_events(self):
        try:
            url = https_url(self.inputs['koth_url'].text)
            self.persist()
        except Exception as error:
            self.say(str(error))
            return
        from koth_client import list_events
        def show(events):
            lines = [f"#{event.get('id', '?')} · {event.get('name', event.get('title', 'Evento'))}" for event in events[:30]]
            self.events.text = '\n'.join(lines) or 'No hay eventos disponibles.'
            self.events.height = dp(max(140, len(lines) * 30))
            self.say('Eventos consultados. Entrar en la cola se habilitará después de validar NetPad.')
        self.run_job(lambda: list_events(url), show)

    def login(self):
        if self.auth_timer:
            self.say('Hay una operación de cuenta en curso.')
            return
        self.account.acct_login_discord()
        self.say('Completa el login en el navegador. Puedes volver a esta app después.')
        self.watch_account()

    def watch_account(self):
        if self.auth_timer is None:
            self.login_button.disabled = True
            self.auth_timer = Clock.schedule_interval(self.drain_account, 0.5)

    def drain_account(self, _):
        import queue
        try:
            _, operation, ok, error = self.account.q.get_nowait()
        except queue.Empty:
            return
        self.auth_timer.cancel()
        self.auth_timer = None
        self.login_button.disabled = False
        account = self.account.account or {}
        name = account.get('nick') or account.get('username') or 'Cuenta Discord'
        self.account_label.text = f'Sesión: {name}' if ok and self.account.session else 'Sin sesión verificada'
        self.say(f'Cuenta: {operation} completado.' if ok else str(error))

    def cancel_login(self):
        self.account.acct_cancel_login()

    def watch_host(self):
        if self.host_timer is None:
            self.host_timer = Clock.schedule_interval(self.refresh_host, 1)

    def refresh_host(self, _=0):
        path = Path(self.user_data_dir) / 'host-status.json'
        state = load_preferences(path)
        self.host_status.text = state.get('message', 'Host detenido.')
        self.client_status.text = self.host_status.text
        if state.get('phase') in ('starting', 'preparing', 'waiting', 'playing', 'stopping'):
            updated = state.get('time')
            if isinstance(updated, (int, float)) and time.time() - updated > 12:
                self.host_status.text += '\nSin actualización reciente: revisa batería y bloqueo de pantalla.'
                self.client_status.text = self.host_status.text

    def start_host(self):
        self.start_session('host')

    def start_client(self):
        self.start_session('guest')

    def start_session(self, role):
        if platform != 'android':
            self.say('El servicio host se inicia desde la APK Android.')
            return
        if self.overlay.active:
            from jnius import autoclass
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            Settings = autoclass('android.provider.Settings')
            if not Settings.canDrawOverlays(activity):
                Intent, Uri = autoclass('android.content.Intent'), autoclass('android.net.Uri')
                activity.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                               Uri.parse('package:' + activity.getPackageName())))
                self.say('Permite Mostrar sobre otras apps, vuelve y pulsa Crear partida.')
                return
        from host import prepare_files, ACTIVE
        state = load_preferences(Path(self.user_data_dir) / 'host-status.json')
        if state.get('phase') in ACTIVE:
            from jnius import autoclass
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            Context = autoclass('android.content.Context')
            manager = activity.getSystemService(Context.ACTIVITY_SERVICE)
            running = manager.getRunningServices(100)
            if any(running.get(i).service.getClassName().endswith('.ServiceHost') for i in range(running.size())):
                self.say('Ya hay una partida activa. Deténla antes de crear otra.')
                return
        try:
            slot = int(self.inputs['pine_slot'].text)
            if not 1 <= slot <= 65535:
                raise ValueError('Puerto PINE inválido.')
            address = self.inputs['zt_address'].text.strip()
            selector = self.host_transport if role == 'host' else self.client_transport
            transport = 'server' if selector.text == 'Servidor UN5' else 'direct'
            if address and transport == 'direct':
                address = validate_address(address)
            game = self.game.text if role == 'host' else self.client_game.text
            host_ip = validate_address(self.host_ip.text) if role == 'guest' and transport == 'direct' else ''
            room_id = self.room_input.text.strip() if role == 'guest' and transport == 'server' else ''
            if role == 'guest' and transport == 'server':
                if not room_id:
                    raise ValueError('Selecciona o introduce una sala.')
                if not self.account.session:
                    raise ValueError('Inicia sesión con Discord para entrar al servidor principal.')
            self.persist()
        except Exception as error:
            self.say(str(error))
            return
        config = {'directory': self.user_data_dir, 'game': game, 'pine_slot': slot,
                  'address': address, 'transport': transport, 'role': role, 'host_ip': host_ip, 'room_id': room_id,
                  'nick': (self.account.account or {}).get('nick') or (('Android P1' if role == 'host' else 'Android P2') if transport == 'server' else ('Player1' if role == 'host' else 'Player2')),
                  'overlay': self.overlay.active,
                  'stop_file': str(Path(self.user_data_dir) / 'host.stop')}
        def launch(_):
            import json
            from jnius import autoclass
            from appdata import write_json
            from android.permissions import request_permissions
            request_permissions(['android.permission.POST_NOTIFICATIONS'])
            Path(config['stop_file']).unlink(missing_ok=True)
            (Path(self.user_data_dir) / 'host-room.json').unlink(missing_ok=True)
            write_json(Path(self.user_data_dir) / 'host-status.json',
                       {'phase': 'starting', 'message': 'Servicio iniciando…'}, private=True)
            service = autoclass('org.un5.narutonetplay.ServiceHost')
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            service.start(activity, '', 'Naruto Netplay · Host P1', 'Partida activa · UDP 47400', json.dumps(config))
            self.say('Vuelve a ARMSX2 y pulsa Reanudar. El servicio prepara la partida.')
            self.open_emulator()
        self.run_job(lambda: prepare_files(self.user_data_dir, game), launch)

    def stop_host(self):
        (Path(self.user_data_dir) / 'host.stop').touch()
        self.say('Parada solicitada. Vuelve a ARMSX2 para liberar el juego.')

    def open_emulator(self):
        if platform != 'android':
            self.say('Abre ARMSX2 en el teléfono.')
            return
        from jnius import autoclass
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        manager = activity.getPackageManager()
        for package in ('come.nanodata.armsx2', 'com.armsx2', 'com.armsx2.nightly'):
            intent = manager.getLaunchIntentForPackage(package)
            if intent is not None:
                activity.startActivity(intent)
                return
        self.say('Abre ARMSX2 manualmente y pulsa Reanudar.')

    def logout(self):
        if self.auth_timer:
            self.say('Cancela primero el login y espera a que termine.')
            return
        self.account.acct_logout()
        self.watch_account()

    def on_pause(self):
        # Allows browser OAuth round-trip; not a foreground service or netplay guarantee.
        if self.host_timer:
            self.host_timer.cancel()
            self.host_timer = None
        return True

    def on_resume(self):
        self.watch_host()
        self.refresh_host()

    def on_stop(self):
        self.closed = True
        self.account.acct_cancel_login()
        if self.auth_timer:
            self.auth_timer.cancel()
        if self.host_timer:
            self.host_timer.cancel()
        self.worker.shutdown(wait=False, cancel_futures=True)
        self.persist()
    
    def refresh_rooms(self):
        from netlink import Api, DEFAULT_API_URL
        def show(rooms):
            self.room_choices = {f"{r['id']} · {r.get('nick', 'P1')} · {r.get('game', '').upper()}": r
                                 for r in rooms if r.get('status') == 'waiting'}
            self.rooms_box.clear_widgets()
            if not self.room_choices:
                self.label_in(self.rooms_box, 'No hay jugadores esperando en este momento.', 14, 55)
            for label in list(self.room_choices)[:30]:
                self.button(self.rooms_box, label, lambda text=label: self.select_client_room(None, text))
            self.say(f'{len(self.room_choices)} salas disponibles.')
        self.run_job(lambda: Api(DEFAULT_API_URL).list_rooms(), show)

    def select_client_room(self, _, text):
        room = self.room_choices.get(text)
        if room:
            self.room_input.text = room['id']
            if room.get('game') in ('un5', 'un6'):
                self.client_game.text = room['game']

    def on_transport_change(self, spinner, text):
        self.transport_container.clear_widgets()

        if text == 'Directo / ZeroTier':
            self.transport_container.add_widget(self.direct_box)

        elif text == 'Servidor UN5':
            self.transport_container.add_widget(self.server_box)
            if hasattr(self, 'status') and not self.busy:
                self.refresh_rooms()


if __name__ == '__main__':
    MobileApp().run()
