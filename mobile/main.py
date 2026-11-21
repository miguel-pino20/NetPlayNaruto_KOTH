"""Naruto Netplay mobile foundation (Kivy/Python)."""
import hashlib
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from weakref import WeakKeyDictionary

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
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.utils import platform
from mobile_locale import LANGUAGES, set_language, tr
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
                        raise ValueError(tr('Discord debe abrirse mediante HTTPS.'))
                    Intent = autoclass('android.content.Intent')
                    Uri = autoclass('android.net.Uri')
                    activity = autoclass('org.kivy.android.PythonActivity').mActivity
                    activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                    return True
            webbrowser.register('android', None, AndroidBrowser(), preferred=True)
        from appdata import DATA_DIR
        self.prefs_path = DATA_DIR / 'mobile.json'
        self.prefs = load_preferences(self.prefs_path)
        self.language = set_language(self.prefs.get('language'))
        self.localized_widgets = WeakKeyDictionary()
        self.changing_language = False
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mobile-api')
        self.busy = False
        self.closed = False
        self.auth_timer = None
        self.discord_verified = False
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
        tabs = TabbedPanel(do_default_tab=False, tab_width=dp(88))
        self.connection = self.page(tabs, 'Conexión')
        self.available_release = None
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        row.add_widget(self.label('Idioma', 48, 16))
        language = Spinner(text=LANGUAGES[self.language], values=tuple(LANGUAGES.values()))
        language.bind(text=self.change_language)
        row.add_widget(language)
        self.connection.add_widget(row)
        version = self.label_in(self.connection, '', 16, 36)
        self.set_text(version, 'Versión {version}', version=VERSION)
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
        self.host_transport = self.transport_spinner(self.prefs.get('transport'))
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
        self.client_transport = self.transport_spinner(self.prefs.get('client_transport'))
        client.add_widget(self.client_transport)
        self.transport_container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10))
        self.transport_container.bind(minimum_height=self.transport_container.setter('height'))
        client.add_widget(self.transport_container)
        self.direct_box = BoxLayout(orientation='vertical', spacing=dp(10), size_hint_y=None)
        self.direct_box.bind(minimum_height=self.direct_box.setter('height'))
        self.label_in(self.direct_box, 'IPv4 del host P1 · puerto 47400', 14, 32)
        self.host_ip = TextInput(text=self.prefs.get('guest_host', ''),
                                 multiline=False, size_hint_y=None, height=dp(48))
        self.set_text(self.host_ip, 'IP del host', property_name='hint_text')
        self.direct_box.add_widget(self.host_ip)
        self.server_box = BoxLayout(orientation='vertical', spacing=dp(10), size_hint_y=None)
        self.server_box.bind(minimum_height=self.server_box.setter('height'))
        self.button(self.server_box, 'Actualizar salas UN5', self.refresh_rooms)
        self.selected_room_id = ''
        self.rooms_box = BoxLayout(orientation='vertical', spacing=dp(6), size_hint_y=None)
        self.rooms_box.bind(minimum_height=self.rooms_box.setter('height'))
        self.label_in(self.rooms_box, 'Pulsa Actualizar salas para buscar jugadores.', 14, 50)
        self.server_box.add_widget(self.rooms_box)
        self.client_transport.bind(text=self.on_transport_change)
        self.on_transport_change(self.client_transport, self.client_transport.text)
        self.button(client, 'Conectar como jugador 2', self.start_client)
        self.button(client, 'Desconectar', self.stop_host)
        self.button(client, 'Volver a ARMSX2', self.open_emulator)
        self.client_status = self.label_in(client, 'Sin conexión.', 14, 150)
        self.label_in(client, 'Usa tus controles locales del mando 1: netplay los asigna al jugador 2. '
                      'Ambos puertos virtuales se preparan como DualShock 2.', 14, 100)
        client.bind(on_release=lambda *_: self.refresh_rooms() if self.transport_mode(self.client_transport) == 'server' and not self.busy else None)

        koth = self.page(tabs, 'KOTH')
        self.field(koth, 'koth_url', 'Servidor KOTH (HTTPS)', 'https://narutimateonline.servegame.com')
        self.button(koth, 'Actualizar eventos', self.list_events)
        self.koth_create = self.button(koth, 'Crear evento casual', self.create_casual)
        self.koth_owner_scope = None
        self.koth_owned = set()
        self.koth_choices = {}
        self.koth_events_url = None
        self.koth_selected_id = None
        self.koth_events_box = BoxLayout(orientation='vertical', spacing=dp(6), size_hint_y=None)
        self.koth_events_box.bind(minimum_height=self.koth_events_box.setter('height'))
        self.label_in(self.koth_events_box, 'Pulsa Actualizar eventos para buscar torneos.', 14, 50)
        koth.add_widget(self.koth_events_box)
        self.koth_game = Spinner(text=self.prefs.get('koth_game', self.game.text), values=('un5', 'un6'),
                                 size_hint_y=None, height=dp(48))
        koth.add_widget(self.koth_game)
        self.koth_start = self.button(koth, 'Iniciar evento casual', self.start_casual)
        self.koth_join = self.button(koth, 'Inscribirme y conectar', self.join_koth)
        self.button(koth, 'Volver a ARMSX2', self.open_emulator)
        self.button(koth, 'Desconectar de KOTH', self.stop_koth)
        self.koth_status = self.label_in(koth, 'KOTH desconectado.', 14, 110)
        self.koth_info = self.label_in(koth, '', 14, 92)
        self.inputs['koth_url'].bind(text=self.refresh_koth_entry)
        self.refresh_koth_entry()
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
        widget = Label(size_hint_y=None, height=dp(height), font_size=dp(size),
                       halign='left', valign='middle')
        self.set_text(widget, text)
        widget.bind(size=lambda instance, value: setattr(instance, 'text_size', (value[0], value[1])))
        return widget

    def label_in(self, parent, text, size=16, height=48):
        widget = self.label(text, height, size)
        parent.add_widget(widget)
        return widget

    def page(self, tabs, title):
        tab = TabbedPanelItem()
        self.set_text(tab, title)
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
        button = Button(size_hint_y=None, height=dp(48), font_size=dp(15), halign='center', valign='middle')
        button.bind(size=lambda widget, size: setattr(widget, 'text_size', (size[0] - dp(12), size[1])))
        self.set_text(button, text)
        button.bind(on_release=lambda *_: action())
        parent.add_widget(button)
        return button

    def set_text(self, widget, message, *, property_name='text', **values):
        self.localized_widgets[widget] = (property_name, message, values)
        setattr(widget, property_name, tr(message, **values))

    def say(self, message, **values):
        if not self.closed:
            self.set_text(self.status, str(message)[:1400], **values)

    def transport_spinner(self, mode):
        values = self.transport_labels()
        return Spinner(text=values[1] if mode == 'direct' else values[0], values=values,
                       size_hint_y=None, height=dp(48))

    @staticmethod
    def transport_labels():
        return tr('Servidor UN5'), tr('Directo / ZeroTier')

    @staticmethod
    def transport_mode(spinner):
        return 'direct' if spinner.text == spinner.values[1] else 'server'

    def change_language(self, _, text):
        from appdata import write_json
        self.language = set_language(next(code for code, label in LANGUAGES.items() if label == text))
        self.prefs['language'] = self.language
        write_json(self.prefs_path, self.prefs, private=True)
        for widget, (property_name, message, values) in list(self.localized_widgets.items()):
            setattr(widget, property_name, tr(message, **values))
        self.changing_language = True
        try:
            for spinner in (self.host_transport, self.client_transport):
                mode = self.transport_mode(spinner)
                spinner.values = self.transport_labels()
                spinner.text = spinner.values[1] if mode == 'direct' else spinner.values[0]
        finally:
            self.changing_language = False
        self.refresh_host()

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
        self.prefs['language'] = self.language
        self.prefs['game'] = self.game.text
        self.prefs['koth_game'] = self.koth_game.text
        self.prefs['overlay'] = self.overlay.active
        self.prefs['transport'] = self.transport_mode(self.host_transport)
        self.prefs['client_transport'] = self.transport_mode(self.client_transport)
        self.prefs['client_game'] = self.client_game.text
        self.prefs['guest_host'] = self.host_ip.text.strip()
        write_json(self.prefs_path, self.prefs, private=True)

    def save_connection(self):
        try:
            slot = int(self.inputs['pine_slot'].text)
            if not 1 <= slot <= 65535:
                raise ValueError(tr('Puerto PINE inválido.'))
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
        self.set_text(self.update_label, 'Buscando actualizaciones…')
        def show(result):
            release, error = result
            if error:
                self.set_text(self.update_label, 'No se pudo comprobar: {error}', error=error)
                return
            self.say('Consulta de actualizaciones completada.')
            self.available_release = release
            self.update_download_button.disabled = release is None
            self.set_text(self.update_label, 'Disponible: {version}' if release else
                          'No hay una actualización posterior a {version}',
                          version=release.version if release else VERSION)
            if release and automatic:
                content = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))
                prompt = self.label('', 70)
                self.set_text(prompt, 'Nueva versión {version}. ¿Descargar APK?', version=release.version)
                content.add_widget(prompt)
                popup = Popup(content=content,
                              size_hint=(0.92, None), height=dp(240))
                self.set_text(popup, 'Actualización disponible', property_name='title')
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
        self.set_text(self.update_label, 'Descargando {version} y verificando SHA256…', version=release.version)
        def fetch():
            try:
                return download_update(self.user_data_dir, release), ''
            except Exception as error:
                return None, str(error)
        def ready(result):
            _, error = result
            if error:
                self.set_text(self.update_label, 'No se pudo descargar: {error}', error=error)
                self.say(error)
                self.update_install_button.disabled = True
                return
            self.set_text(self.update_label, 'APK {version} verificado. Pulsa Instalar actualización.', version=release.version)
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
        self.say('Descargando y verificando estado {game}…', game=game.upper())
        self.run_job(lambda: download_state(self.user_data_dir, game), self.say)

    def test_pine(self):
        slot = self.inputs['pine_slot'].text
        self.run_job(lambda: pine_diagnostics(slot, android=platform == 'android'), self.say)

    def refresh_koth_entry(self, *_):
        source = self.inputs['koth_url'].text.strip().rstrip('/')
        session = self.account.session if self.discord_verified else None
        self.koth_create.disabled = not session
        event = self.koth_choices.get(self.koth_selected_id, {})
        self.koth_start.disabled = not (
            session and self.koth_owner_scope == (source, session) and self.koth_events_url == source
            and event.get('casual') and event.get('status') == 'draft' and event['id'] in self.koth_owned)
        self.koth_join.disabled = True
        if not self.discord_verified or not self.account.session:
            self.set_text(self.koth_info, 'Inicia sesión con Discord para inscribirte y conectar.')
        elif self.koth_events_url != self.inputs['koth_url'].text.strip().rstrip('/'):
            self.set_text(self.koth_info, 'Actualiza los eventos del servidor KOTH.')
        elif self.koth_selected_id not in self.koth_choices:
            self.set_text(self.koth_info, 'Selecciona un evento disponible.')
        else:
            self.koth_join.disabled = False
            self.set_text(self.koth_info, 'Si tu IP de ZeroTier registrada cambia, perderás hasta 1 punto.')

    def list_events(self):
        try:
            source = self.inputs['koth_url'].text.strip().rstrip('/')
            url = https_url(source)
            self.persist()
        except ValueError as error:
            self.say(str(error))
            return
        from discord_auth import AccountError
        from koth_client import list_events, management_access
        session = self.account.session if self.discord_verified else None

        def fetch():
            events = list_events(url)
            try:
                owned = management_access(url, session)['casual_ids'] if session else []
            except AccountError as error:
                return events, [], str(error)
            return events, owned, None

        def show(result):
            if source != self.inputs['koth_url'].text.strip().rstrip('/'):
                return
            events, owned, error = result
            self.koth_owner_scope = (source, session)
            self.koth_owned = set(owned)
            self.show_koth_events(source, events)
            if error:
                self.say(error)
            else:
                self.say('Eventos disponibles: {count}', count=len(self.koth_choices))

        self.run_job(fetch, show)

    def show_koth_events(self, source, events):
        statuses = {'draft': '{event} · Preparación', 'running': '{event} · En curso'}
        if self.koth_events_url != source:
            self.koth_selected_id = None
        self.koth_choices = {event['id']: event for event in events if event.get('status') in statuses}
        self.koth_events_url = source
        if self.koth_selected_id not in self.koth_choices:
            self.koth_selected_id = None
        self.koth_events_box.clear_widgets()
        if not self.koth_choices:
            self.label_in(self.koth_events_box, 'No hay eventos disponibles.', 14, 50)
        for event_id, event in self.koth_choices.items():
            button = ToggleButton(group=self.koth_events_box, allow_no_selection=False,
                                  state='down' if event_id == self.koth_selected_id else 'normal',
                                  size_hint_y=None, height=dp(48), font_size=dp(15))
            self.set_text(button, statuses[event['status']], event=event['name'])
            button.bind(on_release=lambda _, selected=event_id: self.select_koth_event(selected))
            self.koth_events_box.add_widget(button)
        self.refresh_koth_entry()

    def create_casual(self):
        if self.koth_create.disabled or self.busy:
            return
        try:
            source = self.inputs['koth_url'].text.strip().rstrip('/')
            https_url(source)
        except ValueError as error:
            self.say(str(error))
            return
        session = self.account.session
        content = BoxLayout(orientation='vertical', padding=dp(8), spacing=dp(4))
        fields = []
        for label, default in [('Nombre del evento', ''), ('Puntos para ganar (1–1000)', '5'),
                               ('Cupo de jugadores (2–100)', '8')]:
            self.label_in(content, label, 14, 26)
            field = TextInput(text=default, multiline=False, input_filter='int' if default else None)
            content.add_widget(field)
            fields.append(field)
        error_label = self.label_in(content, '', 14, 44)
        popup = Popup(content=content, size_hint=(0.92, 0.85))
        self.set_text(popup, 'Crear evento casual', property_name='title')

        def submit():
            if self.busy:
                return
            name = fields[0].text.strip()
            try:
                points, capacity = (int(field.text) for field in fields[1:])
                if not 1 <= len(name) <= 150 or not 1 <= points <= 1000 or not 2 <= capacity <= 100:
                    raise ValueError
            except ValueError:
                self.set_text(error_label, 'Revisa el nombre, la meta y el cupo.')
                return
            popup.dismiss()
            self.manage_casual(source, session, {'name': name, 'target_points': points, 'max_participants': capacity})

        self.button(content, 'Crear evento casual', submit)
        self.button(content, 'Cancelar', popup.dismiss)
        popup.open()

    def start_casual(self):
        if self.koth_start.disabled or self.busy:
            return
        self.manage_casual(self.koth_events_url, self.account.session, {'action': 'start'},
                           self.koth_choices[self.koth_selected_id])

    def manage_casual(self, source, session, body, event=None):
        from koth_client import get_event, management_command
        def current():
            return (self.discord_verified and session == self.account.session
                    and source == self.inputs['koth_url'].text.strip().rstrip('/'))
        if not current():
            return

        def submit():
            if event:
                # Enrollment changes the version while the organizer is waiting.
                latest = get_event(source, event['id'])
                return management_command(source, session, dict(body, version=latest['version']), event)
            return management_command(source, session, body)

        def show(result):
            if not current():
                return
            choices = dict(self.koth_choices) if self.koth_events_url == source else {}
            choices[result['id']] = result
            if self.koth_owner_scope != (source, session):
                self.koth_owned.clear()
            self.koth_owner_scope = (source, session)
            self.koth_owned.add(result['id'])
            self.koth_events_url = source
            self.koth_selected_id = result['id']
            self.show_koth_events(source, choices.values())
            self.say('Evento iniciado: {event}.' if event else 'Evento creado: {event}.', event=result['name'])

        self.run_job(submit, show)

    def select_koth_event(self, event_id):
        self.koth_selected_id = event_id
        self.refresh_koth_entry()

    def join_koth(self):
        if self.busy:
            self.say('Espera a que termine la consulta actual.')
            return
        self.refresh_koth_entry()
        if self.koth_join.disabled:
            return
        from appdata import DATA_DIR
        from koth_client import MembershipStore, enroll
        try:
            url = https_url(self.koth_events_url)
            configured_address = self.inputs['zt_address'].text.strip()
            if not configured_address:
                self.say('KOTH requiere tu IPv4 de ZeroTier. Configúrala en la pestaña Conexión.')
                return
            try:
                address = validate_address(configured_address)
            except ValueError as error:
                raise ValueError(tr('Revisa la IPv4 de ZeroTier en la pestaña Conexión.')) from error
            self.persist()
        except (ValueError, OSError) as error:
            self.say(str(error))
            return
        if platform == 'android' and self.active_mobile_session():
            self.say('Ya hay una conexión activa. Desconéctala antes de cambiar de evento o IP.')
            return
        try:
            slot = int(self.inputs['pine_slot'].text)
            if not 1 <= slot <= 65535:
                raise ValueError
        except ValueError:
            self.say('Revisa el puerto PINE en la pestaña Conexión.')
            return
        session = self.account.session
        account = self.account.account or {}
        name = account.get('nick') or account.get('username') or tr('Cuenta Discord')
        identity = account.get('id')
        if not identity:
            self.say('No se pudo identificar tu cuenta. Vuelve a iniciar sesión con Discord.')
            return
        account_key = hashlib.sha256(str(identity).encode()).hexdigest()
        store = MembershipStore(DATA_DIR / f'mobile-koth-{account_key}.json')
        event = self.koth_choices[self.koth_selected_id]

        config = {'directory': self.user_data_dir, 'game': self.koth_game.text, 'pine_slot': slot,
                  'address': address, 'transport': 'direct', 'role': 'koth', 'url': url,
                  'nick': name, 'overlay': False, 'event_name': event['name'],
                  'stop_file': str(Path(self.user_data_dir) / 'host.stop')}

        def show(result):
            message = 'Inscripción confirmada en {event}. Puntos: {points}.'
            values = {'event': result['event']['name'], 'points': result['points']}
            if result['address_changed']:
                message = 'Inscripción confirmada en {event}. Puntos: {points}. IP actualizada. Puntos descontados: {deducted}.'
                values['deducted'] = result['points_deducted']
            self.say(message, **values)
            if platform == 'android':
                self.launch_mobile_service(dict(config, koth_ticket=result['ticket']), return_to_game=False)

        self.run_job(lambda: enroll(url, event, name, store, netplay_session=session, address=address), show)

    def stop_koth(self):
        state = load_preferences(Path(self.user_data_dir) / 'host-status.json')
        if state.get('role') == 'koth':
            (Path(self.user_data_dir) / 'host.stop').touch()
            self.say('Desconexión de KOTH solicitada.')

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
        name = account.get('nick') or account.get('username') or tr('Cuenta Discord')
        self.discord_verified = bool(ok and self.account.session)
        if self.discord_verified:
            self.set_text(self.account_label, 'Sesión: {name}', name=name)
        else:
            self.set_text(self.account_label, 'Sin sesión verificada')
        self.refresh_koth_entry()
        messages = {'restore': 'Sesión restaurada.', 'login': 'Sesión iniciada.', 'logout': 'Sesión cerrada.'}
        self.say(messages[operation] if ok else str(error))

    def cancel_login(self):
        self.account.acct_cancel_login()

    def watch_host(self):
        if self.host_timer is None:
            self.host_timer = Clock.schedule_interval(self.refresh_host, 1)

    def refresh_host(self, _=0):
        path = Path(self.user_data_dir) / 'host-status.json'
        state = load_preferences(path)
        message = state.get('message')
        self.host_status.text = message or tr('Host detenido.')
        self.client_status.text = message or tr('Sin conexión.')
        self.koth_status.text = (message if state.get('role') == 'koth' else None) or tr('KOTH desconectado.')
        if state.get('phase') in ('starting', 'preparing', 'waiting', 'playing', 'stopping'):
            updated = state.get('time')
            if isinstance(updated, (int, float)) and time.time() - updated > 12:
                self.host_status.text += '\n' + tr('Sin actualización reciente: revisa batería y bloqueo de pantalla.')
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
        from host import prepare_files
        if self.active_mobile_session():
            self.say('Ya hay una partida activa. Deténla antes de crear otra.')
            return
        try:
            slot = int(self.inputs['pine_slot'].text)
            if not 1 <= slot <= 65535:
                raise ValueError(tr('Puerto PINE inválido.'))
            address = self.inputs['zt_address'].text.strip()
            selector = self.host_transport if role == 'host' else self.client_transport
            transport = self.transport_mode(selector)
            if address and transport == 'direct':
                address = validate_address(address)
            game = self.game.text if role == 'host' else self.client_game.text
            host_ip = validate_address(self.host_ip.text) if role == 'guest' and transport == 'direct' else ''
            room_id = self.selected_room_id if role == 'guest' and transport == 'server' else ''
            if role == 'guest' and transport == 'server':
                if not room_id:
                    raise ValueError(tr('Selecciona una sala de la lista.'))
                if not self.account.session:
                    raise ValueError(tr('Inicia sesión con Discord para entrar al servidor principal.'))
            self.persist()
        except Exception as error:
            self.say(str(error))
            return
        config = {'directory': self.user_data_dir, 'game': game, 'pine_slot': slot,
                  'address': address, 'transport': transport, 'role': role, 'host_ip': host_ip, 'room_id': room_id,
                  'nick': (self.account.account or {}).get('nick') or (('Android P1' if role == 'host' else 'Android P2') if transport == 'server' else ('Player1' if role == 'host' else 'Player2')),
                  'overlay': self.overlay.active,
                  'stop_file': str(Path(self.user_data_dir) / 'host.stop')}
        self.run_job(lambda: prepare_files(self.user_data_dir, game),
                     lambda _: self.launch_mobile_service(config))

    def active_mobile_session(self):
        from host import ACTIVE
        state = load_preferences(Path(self.user_data_dir) / 'host-status.json')
        if state.get('phase') not in ACTIVE:
            return False
        from jnius import autoclass
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        context = autoclass('android.content.Context')
        running = activity.getSystemService(context.ACTIVITY_SERVICE).getRunningServices(100)
        return any(running.get(i).service.getClassName().endswith('.ServiceHost') for i in range(running.size()))

    def launch_mobile_service(self, config, return_to_game=True):
        import json
        from jnius import autoclass
        from appdata import write_json
        from android.permissions import request_permissions
        request_permissions(['android.permission.POST_NOTIFICATIONS'])
        Path(config['stop_file']).unlink(missing_ok=True)
        (Path(self.user_data_dir) / 'host-room.json').unlink(missing_ok=True)
        write_json(Path(self.user_data_dir) / 'host-status.json',
                   {'phase': 'starting', 'role': config['role'], 'message': tr('Servicio iniciando…')}, private=True)
        config = dict(config, language=self.language)
        service = autoclass('org.un5.narutonetplay.ServiceHost')
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        title = 'Naruto Netplay · KOTH' if config['role'] == 'koth' else 'Naruto Netplay'
        service.start(activity, '', title, tr('Vuelve a ARMSX2 y pulsa Reanudar.'), json.dumps(config))
        if return_to_game:
            self.say('Vuelve a ARMSX2 y pulsa Reanudar. El servicio prepara la partida.')
            self.open_emulator()

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
        self.discord_verified = False
        self.refresh_koth_entry()
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
            waiting = [room for room in rooms if room.get('status') == 'waiting']
            visible_rooms = waiting[:30]
            if not any(room['id'] == self.selected_room_id for room in visible_rooms):
                self.selected_room_id = ''
            self.rooms_box.clear_widgets()
            if not visible_rooms:
                self.label_in(self.rooms_box, 'No hay jugadores esperando en este momento.', 14, 55)
            for room in visible_rooms:
                selected = room['id'] == self.selected_room_id
                if selected:
                    self.select_client_room(room)
                label = f"{room['id']} · {room.get('nick', 'P1')} · {room.get('game', '').upper()}"
                button = ToggleButton(text=label, group=self.rooms_box, allow_no_selection=False,
                                      state='down' if selected else 'normal',
                                      size_hint_y=None, height=dp(48), font_size=dp(15))
                button.bind(on_release=lambda _, choice=room: self.select_client_room(choice))
                self.rooms_box.add_widget(button)
            self.say('Salas disponibles: {count}', count=len(waiting))
        self.run_job(lambda: Api(DEFAULT_API_URL).list_rooms(), show)

    def select_client_room(self, room):
        self.selected_room_id = room['id']
        if room.get('game') in ('un5', 'un6'):
            self.client_game.text = room['game']

    def on_transport_change(self, spinner, _):
        if self.changing_language:
            return
        self.transport_container.clear_widgets()

        if self.transport_mode(spinner) == 'direct':
            self.transport_container.add_widget(self.direct_box)

        else:
            self.transport_container.add_widget(self.server_box)
            if hasattr(self, 'status') and not self.busy:
                self.refresh_rooms()


if __name__ == '__main__':
    MobileApp().run()
