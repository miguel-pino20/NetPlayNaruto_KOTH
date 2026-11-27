"""Naruto Netplay mobile foundation (Kivy/Python)."""
import hashlib
import os
import sys
import time
from unicodedata import combining, normalize
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.utils import platform
from mobile_locale import HELP_GUIDES, LANGUAGES, set_language, tr
from backend import (active_events, appearance_store, cache_appearance, configure_storage, discover_zerotier_rooms, event_match, history_portraits,
                     https_url, load_preferences, make_account, owned_appearance, pine_diagnostics,
                     resolve_zerotier_host, validate_address, zerotier_prefix)


class MobileApp(App):
    title = 'Naruto Netplay · ' + VERSION
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
        from koth_client import DEFAULT_URL
        saved_server = self.prefs.get('koth_url')
        try:
            self.koth_url = https_url(saved_server) if isinstance(saved_server, str) and saved_server.strip() else DEFAULT_URL
        except ValueError:
            self.koth_url = DEFAULT_URL
        self.language = set_language(self.prefs.get('language'))
        self.localized_widgets = WeakKeyDictionary()
        self.changing_language = False
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mobile-api')
        self.store_preview_worker = ThreadPoolExecutor(max_workers=3, thread_name_prefix='store-preview')
        self.busy = False
        self.closed = False
        self.auth_timer = None
        self.pending_casual_source = None
        self.discord_verified = False
        self.host_timer = None
        self.account = make_account('https://un5netplay.duckdns.org')
        self.inputs = {}
        self.host_ip = None
        root = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(8))
        shell = FloatLayout()
        self.backdrop = Image(fit_mode='cover')
        shell.add_widget(self.backdrop)
        with root.canvas.before:
            Color(.045, .067, .12, .79)
            shade = Rectangle()
        root.bind(pos=lambda _, value: setattr(shade, 'pos', value),
                  size=lambda _, value: setattr(shade, 'size', value))
        shell.add_widget(root)

        brand = BoxLayout(size_hint_y=None, height=dp(78), spacing=dp(8))
        brand.add_widget(self.label('NARUTO NETPLAY', 78, 19))
        self.button(brand, 'ARMSX2', self.open_emulator).size_hint_x = .45
        self.character_art = Image(fit_mode='contain', size_hint_x=.55)
        brand.add_widget(self.character_art)
        root.add_widget(brand)
        tabs = self.sections = ScreenManager(transition=NoTransition())
        self.connection = self.page(tabs, 'settings')
        self.label_in(self.connection, 'Ajustes', 24)
        self.label_in(self.connection, 'Cuenta Discord', 20, 36)
        self.account_label = self.label_in(self.connection, 'Sin sesión verificada', 17, 42)
        self.login_button = self.button(self.connection, 'Iniciar sesión con Discord', self.login)
        self.button(self.connection, 'Cancelar login', self.cancel_login)
        self.button(self.connection, 'Cerrar sesión', self.logout)
        self.button(self.connection, 'Abrir tienda de fondos y personajes', self.open_store)
        saved_appearance = self.prefs.get('store_appearance')
        self.store_appearance = saved_appearance if isinstance(saved_appearance, dict) else {}
        self.collection_owner = None
        self.collection_loaded = False
        self.appearance_pickers = {}
        self.collection_note = self.label_in(self.connection, 'Inicia sesión con Discord para ver tu colección.', 14, 44)
        self.collection_button = self.button(self.connection, 'Actualizar colección de la tienda', self.refresh_collection)
        self.collection_button.disabled = True
        self.background_picker = self.appearance_picker(self.connection, 'Fondo', 'background', {
            'Sin imagen': '', 'Naruto Uzumaki': 'naruto', 'Sasuke Uchiha': 'sasuke',
            'Kakashi Hatake': 'kakashi', 'Shikamaru Nara': 'shikamaru',
        }, 'sasuke')
        self.character_picker = self.appearance_picker(self.connection, 'Personaje', 'character', {
            'Sin personaje': '', 'Naruto Uzumaki': 'naruto', 'Sasuke Uchiha': 'sasuke',
            'Kakashi Hatake': 'kakashi',
        }, 'sasuke')
        tabs.get_screen('settings').bind(on_enter=lambda *_: self.open_collection())
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
        self.export_variants = {
            'Original · Slot 1': 'original', 'Personajes transformados · Slot 2': 'transformed',
            'Volumen al 20 % · Slot 3': 'audio20',
        }
        self.export_variant = Spinner(size_hint_y=None, height=dp(48))
        self.connection.add_widget(self.export_variant)
        self.export_game.bind(text=self.update_export_options)
        self.update_export_options()
        self.button(self.connection, 'Descargar estado en Descargas', self.export_state)
        self.label_in(self.connection, 'Se guarda en Descargas/NarutoNetplay. '
                      'Debes pasarlo a ARMSX2 por tu cuenta.', 14, 80)
        self.label_in(self.connection, 'UN6: Original en el slot 1, Personajes transformados en el slot 2 y Volumen al 20 % en el slot 3. UN5 usa el slot 1.', 14, 78)
        self.label_in(self.connection, 'ZeroTier')
        self.field(self.connection, 'zt_address', 'Tu IPv4 de ZeroTier', '')
        self.button(self.connection, 'Guardar configuración', self.save_connection)
        self.label_in(self.connection, 'Conecta y autoriza la red desde ZeroTier.\nPuedes crear una sala desde Partida → Host P1.', 14, 80)
        play = Screen(name='play')
        tabs.add_widget(play)
        play_layout = BoxLayout(orientation='vertical', spacing=dp(6))
        play.add_widget(play_layout)
        play_layout.add_widget(self.label('Partida en línea', 40, 24))
        roles = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.match_roles = ScreenManager(transition=NoTransition())
        for key, label in (('host', 'Host P1'), ('guest', 'Cliente P2')):
            self.nav_button(roles, self.match_roles, key, label)
        play_layout.add_widget(roles)
        play_layout.add_widget(self.match_roles)
        host = self.page(self.match_roles, 'host')
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
        self.button(host, 'Crear partida como jugador 1', self.start_host).background_color = (.22, .39, .78, 1)
        self.button(host, 'Detener partida', self.stop_host)
        self.button(host, 'Volver a ARMSX2', self.open_emulator)
        self.host_status = self.label_in(host, 'Host detenido.', 14, 160)
        self.label_in(host, 'Instala el estado compartido en el slot que indica Ayuda.\n'
                      'La app descarga una copia privada, pero no puede instalarla en ARMSX2 automáticamente.\n'
                      'Servidor UN5: la sala aparece en PC. Directo/ZeroTier: P2 conecta a tu IP, UDP 47400.', 14, 160)
        client = self.page(self.match_roles, 'guest')
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
        self.button(self.direct_box, 'Buscar salas ZeroTier', self.refresh_zerotier_rooms)
        self.zerotier_rooms_box = self.tournament_column(self.direct_box)
        self.ip_label = self.label_in(self.direct_box, 'IPv4 del anfitrión', 14, 42)
        self.host_ip = TextInput(text=self.prefs.get('guest_host', ''),
                                 multiline=False, size_hint_y=None, height=dp(48))
        self.inputs['zt_address'].bind(text=self.update_host_ip_hint)
        self.update_host_ip_hint()
        self.direct_box.add_widget(self.host_ip)
        self.button(self.direct_box, 'Conectar por IP', self.start_client).background_color = (.22, .39, .78, 1)
        self.button(self.direct_box, 'Descargar estado del anfitrión', self.export_zerotier_guest_state)
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
        self.button(self.server_box, 'Conectar como jugador 2', self.start_client)
        self.button(client, 'Desconectar', self.stop_host)
        self.button(client, 'Volver a ARMSX2', self.open_emulator)
        self.client_status = self.label_in(client, 'Sin conexión.', 14, 150)
        self.label_in(client, 'Usa tus controles locales del mando 1: netplay los asigna al jugador 2. '
                      'Ambos puertos virtuales se preparan como DualShock 2.', 14, 100)
        self.match_roles.get_screen('guest').bind(on_enter=lambda *_: self.open_client_role())

        koth = self.page(tabs, 'koth')
        self.koth_category = self.event_categories(koth, 'casual', self.render_koth_events)
        self.koth_events = []
        saved_koth_game = self.prefs.get('koth_game')
        self.koth_default_game = saved_koth_game if saved_koth_game in ('un5', 'un6') else self.game.text
        self.button(koth, 'Actualizar eventos', self.list_events)
        self.koth_create = self.button(koth, 'Crear evento casual', self.create_casual)
        self.koth_owner_scope = None
        self.koth_owned = set()
        self.koth_choices = {}
        self.koth_events_url = None
        self.koth_selected_id = None
        self.koth_events_box = BoxLayout(orientation='vertical', spacing=dp(6), size_hint_y=None)
        self.koth_events_box.bind(minimum_height=self.koth_events_box.setter('height'))
        self.label_in(self.koth_events_box, 'Pulsa Actualizar eventos para buscar eventos KOTH.', 14, 50)
        koth.add_widget(self.koth_events_box)
        self.koth_match_label = self.label_in(koth, '', 14, 36)
        self.label_in(koth, 'Red del combate', 14, 40)
        self.koth_network = Spinner(text='Netplay' if self.prefs.get('koth_transport') == 'relay' else 'ZeroTier',
                                    values=('ZeroTier', 'Netplay'), size_hint_y=None, height=dp(48))
        koth.add_widget(self.koth_network)
        self.koth_start = self.button(koth, 'Iniciar evento casual', self.start_casual)
        self.koth_export = self.button(koth, 'Descargar estado del evento', self.export_koth_state)
        self.koth_join = self.button(koth, 'Inscribirme y conectar', self.join_koth)
        self.button(koth, 'Volver a ARMSX2', self.open_emulator)
        self.button(koth, 'Desconectar de KOTH', self.stop_koth)
        self.koth_status = self.label_in(koth, 'KOTH desconectado.', 14, 110)
        self.koth_info = self.label_in(koth, '', 14, 92)
        self.refresh_koth_entry()
        tournaments = self.page(tabs, 'tournaments')
        self.tournament_category = self.event_categories(tournaments, 'official', self.render_tournaments)
        self.tournament_catalog = []
        self.button(tournaments, 'Actualizar torneos', self.open_tournaments)
        self.tournament_events = self.tournament_column(tournaments)
        self.tournament_details = self.tournament_column(tournaments)
        self.tournament_id = None
        self.button(tournaments, 'Detener partida', self.stop_host)
        self.button(tournaments, 'Volver a ARMSX2', self.open_emulator)
        self.tournament_status = self.label_in(tournaments, 'Sin conexión.', 14, 110)
        history = self.page(tabs, 'history')
        self.label_in(history, 'Historial de peleas', 24)
        self.button(history, 'Actualizar historial', lambda: self.load_history(1))
        self.history_rows = self.tournament_column(history)
        history_nav = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.history_page = 1
        self.history_previous = self.button(history_nav, 'Anterior', lambda: self.load_history(self.history_page - 1))
        self.history_next = self.button(history_nav, 'Siguiente', lambda: self.load_history(self.history_page + 1))
        history.add_widget(history_nav)
        self.reset_history()
        tabs.get_screen('history').bind(on_enter=lambda *_: self.load_history(1))

        help_page = self.page(tabs, 'help')
        self.label_in(help_page, 'Ayuda', 24)
        for title, steps in HELP_GUIDES:
            guide = self.rounded_panel((.09, .14, .23, .98), padding=12)
            self.wrapped_label(guide, title, size=17, bold=True)
            for number, step in enumerate(steps, 1):
                label = self.wrapped_label(guide, '')
                self.set_text(label, step, number=number)
            help_page.add_widget(guide)
        self.label_in(help_page, 'Cuenta Discord', 20, 36)
        self.label_in(help_page, 'El inicio de sesión abre el navegador. Vuelve a Netplay cuando termines.', 14, 68)
        self.button(help_page, 'Abrir cuenta Discord en Ajustes', self.open_account_settings)
        store = self.page(tabs, 'store')
        self.label_in(store, 'Tienda', 24)
        self.button(store, 'Volver a Ajustes', self.open_account_settings)
        category = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.button(category, 'Fondos', lambda: self.load_store('background'))
        self.button(category, 'Personajes', lambda: self.load_store('character'))
        store.add_widget(category)
        self.store_balance = self.label_in(store, '', 16, 40)
        self.store_search = TextInput(multiline=False, size_hint_y=None, height=dp(48), font_size=dp(16))
        self.set_text(self.store_search, 'Buscar por nombre', property_name='hint_text')
        store.add_widget(self.store_search)
        self.store_rows = self.tournament_column(store)
        self.store_data = None
        self.store_previews = []
        self.store_preview_pending = 0
        self.store_scroll = store.parent
        self.refresh_store_cards = Clock.create_trigger(self.render_store_cards, .15)
        self.refresh_store_previews = Clock.create_trigger(self.load_visible_store_previews)
        self.store_search.bind(text=self.refresh_store_cards)
        self.store_scroll.bind(scroll_y=self.refresh_store_previews, size=self.refresh_store_previews)
        tabs.get_screen('store').bind(on_enter=self.refresh_store_previews)
        tabs.current = 'play'
        root.add_widget(tabs)
        self.status = Label(size_hint_y=None, height=dp(56), font_size=dp(13), halign='left', valign='middle')
        self.set_text(self.status, 'Listo. Activa PINE en ARMSX2 antes de probar.')
        status_scroll = ScrollView(size_hint_y=None, height=dp(56))
        self.status.bind(width=lambda widget, value: setattr(widget, 'text_size', (value, None)),
                         texture_size=lambda widget, value: setattr(widget, 'height', max(dp(56), value[1])))
        status_scroll.add_widget(self.status)
        root.add_widget(status_scroll)
        navigation = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(3))
        for key, label in (('play', 'Partida'), ('koth', 'KOTH'), ('tournaments', 'Torneos'),
                           ('history', 'Historial'), ('settings', 'Ajustes'), ('help', 'Ayuda')):
            self.nav_button(navigation, tabs, key, label)
        root.add_widget(navigation)
        if self.account.session:
            self.account.acct_restore()
            self.watch_account()
        self.watch_host()
        if platform == 'android':
            Clock.schedule_once(lambda _: self.check_updates(automatic=True), 2)
        return shell

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
        tab = Screen(name=title)
        scroll = ScrollView()
        content = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10), padding=dp(8))
        content.bind(minimum_height=content.setter('height'))
        scroll.add_widget(content)
        tab.add_widget(scroll)
        tabs.add_widget(tab)
        return content

    def nav_button(self, parent, manager, key, label):
        button = self.button(parent, label, lambda: setattr(manager, 'current', key))
        button.font_size = dp(12)
        button.bind(size=lambda widget, size: setattr(widget, 'text_size', (size[0] - dp(4), size[1])))

        def highlight(*_):
            selected = manager.current == key or (key == 'settings' and manager.current == 'store')
            button.background_color = (.22, .39, .78, 1) if selected else (.10, .15, .25, 1)

        manager.bind(current=highlight)
        highlight()

    def open_account_settings(self):
        self.connection.parent.scroll_y = 1
        self.sections.current = 'settings'

    def open_store(self):
        if not self.appearance_owner():
            self.say('Inicia sesión con Discord para abrir la tienda.')
            return
        if self.busy:
            self.say('Espera a que termine la consulta actual.')
            return
        self.sections.current = 'store'
        self.load_store('background')

    def load_store(self, preference):
        owner, session = self.appearance_owner(), self.account.session
        if not owner or self.busy:
            return
        self.store_data = None
        self.store_previews.clear()
        self.store_rows.clear_widgets()
        self.set_text(self.store_balance, 'Consultando…')

        def show(data):
            if owner != self.appearance_owner() or session != self.account.session or self.sections.current != 'store':
                return
            self.render_store(preference, data)

        self.run_job(lambda: appearance_store(session, preference), show)

    def render_store(self, preference, data):
        self.store_data = preference, data
        self.set_text(self.store_balance, 'Saldo: {points} puntos', points=data['balance'])
        self.render_store_cards()

    @staticmethod
    def store_search_key(value):
        return ''.join(char for char in normalize('NFKD', value.casefold()) if not combining(char))

    def render_store_cards(self, *_):
        if self.store_data is None:
            return
        preference, data = self.store_data
        self.store_rows.clear_widgets()
        self.store_previews = []
        self.store_scroll.scroll_y = 1
        self.button(self.store_rows, 'Actualizar tienda', lambda: self.load_store(preference))
        if not data['items']:
            self.label_in(self.store_rows, 'No hay artículos disponibles.', 14, 48)
            return
        query = self.store_search_key(self.store_search.text.strip())
        items = [item for item in data['items'] if query in self.store_search_key(item['name'])]
        if not items:
            self.label_in(self.store_rows, 'No se encontraron artículos con ese nombre.', 14, 48)
            return
        grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, row_default_height=dp(218), row_force_default=True)
        grid.bind(minimum_height=grid.setter('height'))
        grid.bind(pos=self.refresh_store_previews, size=self.refresh_store_previews)
        self.store_rows.add_widget(grid)
        for item in items:
            cost = tr('En tu colección') if item['owned'] else tr('Gratis') if item['price'] == 0 else tr('{points} puntos', points=item['price'])
            card = self.rounded_panel((.09, .14, .23, .98), padding=8, height=218)
            grid.add_widget(card)
            preview = FloatLayout()
            image = Image(fit_mode='contain', pos_hint={'x': 0, 'y': 0})
            placeholder = Label(font_size=dp(12), color=(.73, .79, .91, 1), pos_hint={'x': 0, 'y': 0})
            self.set_text(placeholder, 'Vista previa')
            preview.add_widget(placeholder)
            preview.add_widget(image)
            card.add_widget(preview)
            self.store_previews.append((item, image, placeholder))
            name = self.wrapped_label(card, item['name'], bold=True)
            name.max_lines = 2
            self.wrapped_label(card, cost, size=13, color=(.73, .79, .91, 1))
            self.button(card, 'Ver artículo', lambda item=item: self.show_store_item(preference, item, data))
        self.refresh_store_previews()

    def load_visible_store_previews(self, *_):
        owner, session = self.appearance_owner(), self.account.session
        if self.closed or not owner or self.store_data is None or self.sections.current != 'store':
            return
        preference, _ = self.store_data
        previews = self.store_previews
        content = self.store_rows.parent
        bottom = content.y + max(0, content.height - self.store_scroll.height) * self.store_scroll.scroll_y
        top = bottom + self.store_scroll.height
        for item, image, placeholder in previews:
            if self.store_preview_pending >= 3:
                break
            if not placeholder.opacity or not bottom - dp(70) <= image.parent.center_y <= top + dp(70):
                continue
            if getattr(image, 'preview_requested', False):
                continue
            image.preview_requested = True
            self.store_preview_pending += 1
            future = self.store_preview_worker.submit(cache_appearance, self.user_data_dir, owner, preference, item, session)

            def finish(_, job=future, target=image, message=placeholder):
                self.store_preview_pending -= 1
                if self.closed:
                    return
                if previews is self.store_previews and owner == self.appearance_owner() and session == self.account.session:
                    try:
                        target.source = str(job.result())
                    except (OSError, ValueError):
                        self.set_text(message, 'Vista previa no disponible')
                    else:
                        message.opacity = 0
                self.refresh_store_previews()

            future.add_done_callback(lambda _, done=finish: Clock.schedule_once(done))

    def show_store_item(self, preference, item, data):
        owner, session = self.appearance_owner(), self.account.session
        if not owner or self.busy:
            return

        def fetch():
            try:
                return cache_appearance(self.user_data_dir, owner, preference, item, session)
            except (OSError, ValueError):
                return None

        def show(path):
            if owner != self.appearance_owner() or session != self.account.session or self.sections.current != 'store':
                return
            content = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(8))
            dialog = Popup(title=item['name'], content=content, size_hint=(.92, None),
                           height=dp(350 if path else 240))
            if path:
                content.add_widget(Image(source=str(path), fit_mode='contain'))
            if item['owned']:
                self.button(content, 'Usar', lambda: (dialog.dismiss(), self.use_store_item(preference, item)))
            elif item['price'] > data['balance']:
                self.label_in(content, 'Puntos insuficientes.', 14, 40)
            else:
                price = self.label_in(content, '', 14, 40)
                self.set_text(price, 'Precio: {points} puntos', points=item['price'])
                self.button(content, 'Confirmar compra' if item['price'] else 'Añadir a mi colección',
                            lambda: (dialog.dismiss(), self.purchase_store_item(preference, item, data)))
            self.button(content, 'Cerrar', dialog.dismiss)
            dialog.open()

        self.run_job(fetch, show)

    def remember_store_item(self, preference, item):
        owner = self.appearance_owner()
        if self.collection_owner not in (None, owner):
            self.reset_collection()
        self.collection_owner = owner
        picker = self.appearance_pickers[preference]
        label = self.store_item_label(item)
        picker.items[label] = item
        picker.values = (*picker.local_choices, *picker.items)
        return picker, label

    def use_store_item(self, preference, item):
        if self.appearance_owner():
            picker, label = self.remember_store_item(preference, item)
            picker.text = label

    def purchase_store_item(self, preference, item, data):
        from discord_auth import AccountError

        owner, session = self.appearance_owner(), self.account.session
        if not owner:
            return

        def purchase():
            try:
                return appearance_store(session, preference, item=item)
            except AccountError as error:
                if str(error) == 'price_changed':
                    raise ValueError(tr('El precio cambió. Actualiza la tienda antes de comprar.')) from None
                if str(error) == 'insufficient_balance':
                    raise ValueError(tr('Puntos insuficientes.')) from None
                raise

        def show(result):
            if owner != self.appearance_owner() or session != self.account.session:
                return
            data['balance'], item['owned'] = result['balance'], True
            self.remember_store_item(preference, item)
            if self.sections.current == 'store':
                self.render_store(preference, data)
            self.say('Artículo añadido a tu colección.')

        self.run_job(purchase, show)

    def appearance_picker(self, parent, title, preference, choices, default):
        self.label_in(parent, title, 14, 28)
        names = {value: name for name, value in choices.items()}
        picker = Spinner(text=names.get(self.prefs.get(preference), names[default]),
                         values=tuple(choices), size_hint_y=None, height=dp(48))
        picker.preference, picker.local_choices = preference, choices
        picker.items = {}
        picker.selection_revision = 0
        picker.local_selection = picker.applied = picker.text
        picker.bind(text=self.select_appearance)
        self.appearance_pickers[preference] = picker
        parent.add_widget(picker)
        self.apply_appearance(picker, picker.applied)
        return picker

    def appearance_owner(self):
        account_id = (self.account.account or {}).get('id')
        return str(account_id) if self.discord_verified and self.account.session and account_id else None

    def appearance_preferences(self, owner):
        selected = self.store_appearance.get(owner)
        if not isinstance(selected, dict):
            selected = {}
            self.store_appearance[owner] = selected
        return selected

    @staticmethod
    def store_item_label(item):
        return f"{item['name']} · {tr('Tienda')} #{item['id']}"

    def apply_appearance(self, picker, label, path=None):
        picker.applied = picker.text = label
        image = self.backdrop if picker.preference == 'background' else self.character_art
        if path is None:
            selection = picker.local_choices[label]
            assets = ROOT / 'assets' if (ROOT / 'pine.py').is_file() else Path(__file__).with_name('assets')
            if picker.preference == 'background':
                path = assets / 'background' / 'characters' / (selection + '.jpg') if selection else None
            elif selection == 'naruto':
                path = assets / 'naruto_mascot.png'
            elif selection:
                path = assets / 'characters' / (selection + '.png')
        image.source = str(path) if path else ''

    def select_appearance(self, picker, label):
        if label == picker.applied:
            return
        if label not in picker.local_choices and self.busy:
            picker.text = picker.applied
            self.say('Espera a que termine la consulta actual.')
            return
        picker.selection_revision += 1
        revision = picker.selection_revision
        owner = self.appearance_owner()
        preference = picker.preference
        if label in picker.local_choices:
            picker.local_selection = label
            self.apply_appearance(picker, label)
            if owner:
                self.appearance_preferences(owner).pop(preference, None)
            self.persist()
            return
        picker.text = picker.applied
        item = picker.items.get(label)
        if not item or not owner or owner != self.collection_owner:
            return
        session = self.account.session

        def show(path):
            if (revision != picker.selection_revision or owner != self.appearance_owner() or session != self.account.session
                    or picker.items.get(label) != item):
                return
            self.apply_appearance(picker, label, path)
            self.appearance_preferences(owner)[preference] = str(item['id'])
            self.persist()
            self.say('Apariencia aplicada.')

        self.run_job(lambda: cache_appearance(self.user_data_dir, owner, preference, item, session), show)

    def reset_collection(self):
        self.collection_owner = None
        self.collection_loaded = False
        for picker in self.appearance_pickers.values():
            picker.items = {}
            self.apply_appearance(picker, picker.local_selection)
            picker.values = tuple(picker.local_choices)
        self.collection_button.disabled = self.appearance_owner() is None
        self.set_text(self.collection_note, 'Inicia sesión con Discord para ver tu colección.'
                      if self.collection_button.disabled else 'Actualiza para ver tus fondos y personajes.')

    def open_collection(self):
        if self.appearance_owner() and not self.collection_loaded and not self.busy:
            self.refresh_collection()

    def refresh_collection(self):
        owner = self.appearance_owner()
        if not owner:
            self.reset_collection()
            return
        session = self.account.session
        selected = dict(self.appearance_preferences(owner))

        def fetch():
            collection = owned_appearance(session)
            images = {}
            for preference, items in collection.items():
                item = items.get(selected.get(preference))
                if item:
                    try:
                        images[preference] = cache_appearance(self.user_data_dir, owner, preference, item, session)
                    except (OSError, ValueError):
                        pass
            return collection, images

        def show(result):
            if owner != self.appearance_owner() or session != self.account.session:
                return
            collection, images = result
            self.collection_owner = owner
            self.collection_loaded = True
            for preference, picker in self.appearance_pickers.items():
                picker.items = {self.store_item_label(item): item
                                for item in collection[preference].values()}
                picker.values = (*picker.local_choices, *picker.items)
                saved = self.appearance_preferences(owner).get(preference)
                label = next((label for label, item in picker.items.items() if str(item['id']) == saved), None)
                if label and preference in images:
                    self.apply_appearance(picker, label, images[preference])
                elif picker.applied not in picker.items:
                    self.apply_appearance(picker, picker.local_selection)
            self.set_text(self.collection_note, 'Colección actualizada.' if any(collection.values())
                          else 'Tu colección aún no tiene fondos ni personajes.')
            self.say('Colección actualizada.')

        self.run_job(fetch, show)

    def reset_history(self):
        self.history_rows.clear_widgets()
        self.history_page = 1
        self.history_previous.disabled = self.history_next.disabled = True
        self.label_in(self.history_rows, 'Actualiza para ver tus peleas.' if self.discord_verified
                      else 'Inicia sesión con Discord en Ajustes para ver tus peleas.', 14, 68)

    def load_history(self, page):
        from discord_auth import api_call
        from koth_client import DEFAULT_URL
        session = self.account.session
        if not self.discord_verified or not session:
            self.reset_history()
            return

        directory = self.user_data_dir
        language = self.language

        def fetch():
            data = api_call(DEFAULT_URL, 'GET', f'/api/netplay/history/?page={page}', follow_redirects=False,
                            extra_headers={'X-Netplay-Session': session, 'Accept-Language': language})
            return data, history_portraits(directory, data['fights'])

        def show(result):
            if session != self.account.session or not self.discord_verified:
                return
            data, portraits = result
            self.history_page = data['page']
            self.history_previous.disabled = self.history_page <= 1
            self.history_next.disabled = self.history_page >= data['pages']
            self.history_rows.clear_widgets()
            if not data['fights']:
                self.label_in(self.history_rows, 'Todavía no hay peleas registradas.', 14, 60)
            for fight in data['fights']:
                self.history_rows.add_widget(self.history_card(fight, portraits))
            self.history_rows.parent.parent.scroll_y = 1
            self.say('Historial actualizado.')

        self.run_job(fetch, show)

    def history_card(self, fight, portraits):
        card = self.rounded_panel((.09, .14, .23, .98), padding=10)
        date = datetime.fromisoformat(fight['date']).astimezone().strftime('%d/%m/%Y %H:%M')
        self.wrapped_label(card, f"{fight['outcome']} · {date}", size=16, bold=True)
        self.wrapped_label(card, fight['event'] or 'Partida casual', color=(.73, .79, .91, 1))
        rival = self.wrapped_label(card, '')
        self.set_text(rival, 'Rival: {name}', name=fight['rival'] or '—')
        matchup = BoxLayout(spacing=dp(6), size_hint_y=None)
        card.add_widget(matchup)
        players = (fight['players'] + [{}, {}])[:2]
        panels = []
        for slot, player in enumerate(players, start=1):
            if slot == 2:
                matchup.add_widget(Label(text='VS', font_size=dp(12), size_hint_x=None, width=dp(24)))
            panel = self.rounded_panel((.14, .21, .34, 1), padding=6)
            panel.pos_hint = {'top': 1}
            matchup.add_widget(panel)
            panels.append(panel)
            self.wrapped_label(panel, f'P{slot}', centered=True, size=12)
            portrait = portraits.get(player.get('portrait'))
            if portrait:
                panel.add_widget(Image(source=str(portrait), fit_mode='contain', size_hint_y=None, height=dp(62)))
            self.wrapped_label(panel, player.get('name') or '—', centered=True, bold=True)
            self.wrapped_label(panel, player.get('character') or 'Personaje sin registrar', centered=True,
                              color=(.73, .79, .91, 1))

        def fit_matchup(*_):
            matchup.height = max(panel.height for panel in panels)

        for panel in panels:
            panel.bind(height=fit_matchup)
        fit_matchup()
        score = fight.get('score')
        if score is not None:
            result = self.wrapped_label(card, '', centered=True, bold=True)
            self.set_text(result, 'P1 {p1} · P2 {p2} · Empates {draws}', **score)
        return card

    @staticmethod
    def rounded_panel(color, *, padding, height=None):
        panel = BoxLayout(orientation='vertical', spacing=dp(4), padding=dp(padding), size_hint_y=None)
        if height is None:
            panel.bind(minimum_height=panel.setter('height'))
        else:
            panel.height = dp(height)
        with panel.canvas.before:
            Color(*color)
            shape = RoundedRectangle(radius=[dp(10)])
        panel.bind(pos=lambda _, value: setattr(shape, 'pos', value),
                   size=lambda _, value: setattr(shape, 'size', value))
        return panel

    def wrapped_label(self, parent, message, *, size=14, centered=False, bold=False, color=(1, 1, 1, 1)):
        label = Label(font_size=dp(size), bold=bold, color=color, halign='center' if centered else 'left',
                      size_hint_y=None, height=dp(22))
        label.bind(width=lambda widget, width: setattr(widget, 'text_size', (width, None)),
                   texture_size=lambda widget, texture: setattr(widget, 'height', max(dp(20), texture[1])))
        self.set_text(label, message)
        parent.add_widget(label)
        return label

    def field(self, parent, key, title, default, numeric=False):
        self.label_in(parent, title, 14, 28)
        field = TextInput(text=str(self.prefs.get(key, default)), multiline=False,
                          size_hint_y=None, height=dp(48), font_size=dp(16))
        if numeric:
            field.input_filter = 'int'
        self.inputs[key] = field
        parent.add_widget(field)

    def button(self, parent, text, action):
        button = Button(size_hint_y=None, height=dp(48), font_size=dp(15), halign='center', valign='middle',
                        background_normal='', background_down='', background_color=(.18, .26, .43, 1))
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
        return 'Netplay', 'ZeroTier'

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
        self.update_export_options()
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
        if self.closed:
            return
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
        self.prefs['koth_url'] = self.koth_url
        self.prefs['game'] = self.game.text
        self.prefs['koth_game'] = self.koth_default_game
        self.prefs['koth_transport'] = 'relay' if self.koth_network.text == 'Netplay' else 'zerotier'
        self.prefs['overlay'] = self.overlay.active
        self.prefs['transport'] = self.transport_mode(self.host_transport)
        self.prefs['client_transport'] = self.transport_mode(self.client_transport)
        self.prefs['client_game'] = self.client_game.text
        self.prefs['guest_host'] = self.host_ip.text.strip()
        for picker in self.appearance_pickers.values():
            self.prefs[picker.preference] = picker.local_choices[picker.local_selection]
        self.prefs['store_appearance'] = self.store_appearance
        write_json(self.prefs_path, self.prefs, private=True)

    def save_connection(self):
        try:
            slot = int(self.inputs['pine_slot'].text)
            if not 1 <= slot <= 65535:
                raise ValueError(tr('Puerto PINE inválido.'))
            if self.inputs['zt_address'].text.strip():
                validate_address(self.inputs['zt_address'].text)
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

    def update_export_options(self, *_):
        un6 = self.export_game.text == 'un6'
        self.export_variant.disabled = not un6
        self.export_variant.values = tuple(tr(label) for label in self.export_variants)
        self.export_variant.text = self.export_variant.values[0] if un6 else tr('UN5 · Slot 1')

    def export_state(self):
        variant = next((key for label, key in self.export_variants.items() if tr(label) == self.export_variant.text), None)
        self.export_match_state(self.export_game.text, variant)

    def export_match_state(self, game, variant=None):
        if platform != 'android':
            self.say('Guardar en Descargas está disponible en Android 10 o posterior.')
            return
        from downloads import download_state
        self.say('Descargando y verificando estado {game}…', game=game.upper())
        self.run_job(lambda: download_state(self.user_data_dir, game, variant=variant), self.say)

    def export_koth_state(self):
        event = self.koth_choices.get(self.koth_selected_id)
        if not event or self.koth_events_url != self.koth_url:
            return
        game, variant = event_match(event, self.koth_default_game)
        self.export_match_state(game, variant)

    def test_pine(self):
        slot = self.inputs['pine_slot'].text
        self.run_job(lambda: pine_diagnostics(slot, android=platform == 'android'), self.say)

    def refresh_koth_entry(self, *_):
        source = self.koth_url
        session = self.account.session if self.discord_verified else None
        event = self.koth_choices.get(self.koth_selected_id, {})
        casual = self.koth_category() == 'casual'
        for button in (self.koth_create, self.koth_start):
            button.opacity = 1 if casual else 0
            button.height = dp(48) if casual else 0
        self.koth_create.disabled = not casual
        self.koth_start.disabled = not (
            session and self.koth_owner_scope == (source, session) and self.koth_events_url == source
            and event.get('casual') and event.get('status') == 'draft' and event['id'] in self.koth_owned)
        try:
            match = event_match(event, self.koth_default_game) if event else None
        except ValueError:
            match = None
        self.koth_export.disabled = not (match and self.koth_events_url == source)
        if match:
            self.set_text(self.koth_match_label, 'Juego: {game}', game=match[0].upper())
        else:
            self.set_text(self.koth_match_label, 'El estado configurado no es compatible.' if event else '')
        self.koth_join.disabled = True
        if not self.discord_verified or not self.account.session:
            self.set_text(self.koth_info, 'Inicia sesión con Discord para inscribirte y conectar.')
        elif self.koth_events_url != self.koth_url:
            self.set_text(self.koth_info, 'Actualiza los eventos del servidor KOTH.')
        elif self.koth_selected_id not in self.koth_choices:
            self.set_text(self.koth_info, 'Selecciona un evento disponible.')
        elif match:
            self.koth_join.disabled = False
            self.set_text(self.koth_info, 'Si tu IP de ZeroTier registrada cambia, perderás hasta 1 punto.')
        else:
            self.set_text(self.koth_info, '')

    def tournament_column(self, parent):
        content = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(6))
        content.bind(minimum_height=content.setter('height'))
        parent.add_widget(content)
        return content

    def tournament_source(self):
        return self.koth_url

    def event_categories(self, parent, default, render):
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        parent.add_widget(row)
        selection = default
        buttons = {}

        def select(category):
            nonlocal selection
            selection = category
            for key, button in buttons.items():
                button.background_color = (.22, .39, .78, 1) if key == selection else (.10, .15, .25, 1)
            render()

        for key, label in (('casual', 'Casual'), ('official', 'Oficial')):
            button = self.button(row, label, lambda key=key: select(key))
            button.background_color = (.22, .39, .78, 1) if key == default else (.10, .15, .25, 1)
            buttons[key] = button
        return lambda: selection

    def open_tournaments(self):
        from koth_client import scheduled_tournaments
        source = self.tournament_source()
        session = self.account.session if self.discord_verified else None

        def show(events):
            verified_session = self.account.session if self.discord_verified else None
            if source != self.tournament_source() or session != verified_session:
                return
            self.tournament_catalog = events
            self.say('Torneos actualizados.')
            self.render_tournaments()

        self.run_job(lambda: scheduled_tournaments(https_url(source), all_statuses=True, session=session), show)

    def render_tournaments(self):
        from koth_client import tournament_label
        source = self.tournament_source()
        events = active_events(self.tournament_catalog, casual=self.tournament_category() == 'casual')
        selected = next((event for event in events if event['id'] == self.tournament_id), None)
        self.tournament_id = None
        self.tournament_details.clear_widgets()
        self.tournament_events.clear_widgets()
        for event in events:
            self.button(self.tournament_events, tournament_label(event) + ' · ' +
                        self.tournament_state(event['status']),
                        lambda event=event: self.select_tournament(source, event))
        if events:
            self.select_tournament(source, selected or events[0])
        else:
            self.label_in(self.tournament_events, 'No hay torneos disponibles.')

    @staticmethod
    def tournament_state(status):
        labels = {'draft': 'Inscripciones', 'running': 'En curso', 'finished': 'Finalizado',
                  'waiting': 'Pendiente', 'ready': 'Listo', 'bye': 'Pase libre', 'cancelled': 'Cancelado'}
        return tr(labels.get(status, status))

    def select_tournament(self, source, event):
        from koth_client import tournament_bracket
        if self.busy or source != self.tournament_source():
            return
        self.tournament_id = event['id']
        panel = self.tournament_details
        panel.clear_widgets()
        self.label_in(panel, event['name'], 19)
        self.run_job(lambda: tournament_bracket(https_url(source), event['id']),
                     lambda data: self.show_tournament(source, event, data))

    def show_tournament(self, source, event, data):
        import webbrowser
        from koth_client import site_url
        if not self.is_current_tournament(source, event):
            return
        panel = self.tournament_details
        status = data.get('status', event.get('status', 'draft'))
        if status not in ('draft', 'running'):
            self.tournament_catalog = [item for item in self.tournament_catalog if item['id'] != event['id']]
            self.render_tournaments()
            return
        try:
            match = event_match(data, self.game.text, event=event)
        except ValueError as error:
            self.label_in(panel, str(error), 14, 42)
            match = None
        if match:
            label = self.label_in(panel, '', 14, 30)
            self.set_text(label, 'Juego: {game}', game=match[0].upper())
        if status == 'draft':
            self.button(panel, 'Inscribirme en el torneo', lambda: self.enroll_tournament(source, event))
        if status == 'running' and match:
            network = None
            if event['format'] == 'round_robin':
                self.label_in(panel, 'Red del combate', 14, 40)
                network = Spinner(text='ZeroTier', values=('ZeroTier', 'Netplay'), size_hint_y=None, height=dp(48))
                panel.add_widget(network)
            self.button(panel, 'Conectar a mi cruce', lambda: self.connect_tournament(
                source, event, data, network.text if network else None))
        self.button(panel, 'Abrir cuadro público', lambda: webbrowser.open(
            f"{site_url(source)}/torneos/{int(event['id'])}/publico/"))
        bracket = self.tournament_column(panel)
        self.label_in(bracket, 'Cuadro del torneo', 17)
        if not data['fixtures']:
            self.label_in(bracket, 'El cuadro todavía no está disponible.')
        stages = {'winners': 'Ganadores', 'losers': 'Perdedores', 'grand_final': 'Gran final',
                  'reset': 'Final decisiva', 'tiebreak': 'Desempate', 'round_robin': 'Todos contra todos'}
        previous = None
        for row in data['fixtures']:
            group = row['stage'], row['round_number']
            if group != previous:
                previous = group
                self.label_in(bracket, tr('{stage} · Ronda {number}', stage=tr(stages.get(group[0], group[0])),
                                         number=group[1]), 15, 34)
            p1, p2 = (self.tournament_player(row, slot) for slot in (1, 2))
            self.label_in(bracket, f"#{row['number']} · {self.tournament_state(row['status'])}\n"
                          f"{p1}  {row['p1_wins']} – {row['p2_wins']}  {p2}", 14, 58)

    @staticmethod
    def tournament_player(row, slot):
        if name := row.get(f'player{slot}__name'):
            return name
        if number := row.get(f'source{slot}__number'):
            return tr('Perdedor #{number}' if row.get(f'source{slot}_loser') else 'Ganador #{number}',
                      number=number)
        return '—'

    def is_current_tournament(self, source, event):
        return source == self.tournament_source() and event['id'] == self.tournament_id

    def enroll_tournament(self, source, event):
        from koth_client import join_tournament
        session = self.account.session if self.discord_verified else None
        if not session:
            self.say('Inicia sesión con Discord para inscribirte.')
            return

        def show(participant):
            if self.is_current_tournament(source, event) and self.account.session == session:
                self.say('Inscripción confirmada en {name} (#{id}).', name=event['name'], id=participant)

        self.run_job(lambda: join_tournament(source, session, event['id']), show)

    def connect_tournament(self, source, event, bracket, network=None):
        from host import prepare_files
        from koth_client import assigned_fixture
        if platform != 'android':
            self.say('El servicio host se inicia desde la APK Android.')
            return
        session = self.account.session if self.discord_verified else None
        if not session:
            self.say('Inicia sesión con Discord para conectar al cruce.')
            return
        if self.active_mobile_session():
            self.say('Ya hay una partida activa. Deténla antes de crear otra.')
            return
        try:
            url = https_url(source)
            preference = {'Netplay': 'relay', 'ZeroTier': 'zerotier'}.get(network, 'direct-only')
            address = '0.0.0.0'
            if preference != 'relay':
                try:
                    address = validate_address(self.inputs['zt_address'].text.strip())
                except ValueError:
                    raise ValueError(tr('Revisa la IPv4 de ZeroTier en la pestaña Conexión.')) from None
            slot = int(self.inputs['pine_slot'].text)
            if not 1 <= slot <= 65535:
                raise ValueError(tr('Puerto PINE inválido.'))
            self.persist()
        except (ValueError, OSError) as error:
            self.say(str(error))
            return

        fallback_game = self.game.text

        def prepare():
            fixture = assigned_fixture(url, session, event['id'])
            if not fixture:
                return None, None
            event_settings = {**event, **{key: bracket[key] for key in ('match_state', 'match_game', 'game')
                                          if bracket.get(key)}}
            match = event_match(fixture, fallback_game, event=event_settings)
            prepare_files(self.user_data_dir, match[0], variant=match[1])
            return fixture, match

        def show(result):
            fixture, match = result
            if (not self.is_current_tournament(source, event) or not self.discord_verified
                    or self.account.session != session):
                return
            if not fixture:
                self.say('Todavía no tienes un cruce listo en este torneo.')
                return
            if self.active_mobile_session():
                self.say('Ya hay una partida activa. Deténla antes de crear otra.')
                return
            role = fixture['role']
            config = {'directory': self.user_data_dir, 'game': match[0], 'pine_slot': slot,
                      'address': address, 'transport': 'direct', 'fixture': {
                          'event_id': fixture['event_id'], 'fixture_id': fixture['fixture_id']},
                      'url': url, 'role': 'host' if role == 'p1' else 'guest',
                      'round_robin': event['format'] == 'round_robin', 'fixture_transport': preference,
                      'nick': fixture[role]['name'], 'overlay': False,
                      'stop_file': str(Path(self.user_data_dir) / 'host.stop')}
            self.launch_mobile_service(config)

        self.run_job(prepare, show)

    def list_events(self):
        try:
            source = self.koth_url
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
            if source != self.koth_url:
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
        if self.koth_events_url != source:
            self.koth_selected_id = None
        self.koth_events_url = source
        self.koth_events = list(events)
        self.render_koth_events()

    def render_koth_events(self):
        statuses = {'draft': '{event} · Preparación', 'running': '{event} · En curso'}
        self.koth_choices = {event['id']: event for event in
                             active_events(self.koth_events, casual=self.koth_category() == 'casual')}
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
        try:
            source = self.koth_url
            https_url(source)
        except ValueError as error:
            self.say(str(error))
            return
        if not self.discord_verified or not self.account.session:
            self.pending_casual_source = source
            if self.auth_timer is None:
                self.login()
            return
        from koth_client import KOTH_STATES

        session = self.account.session
        content = BoxLayout(orientation='vertical', padding=dp(8), spacing=dp(4), size_hint_y=None)
        content.bind(minimum_height=content.setter('height'))
        fields = []
        for label, default in [('Nombre del evento', ''), ('Puntos para ganar (1–1000)', '5'),
                               ('Cupo de jugadores (2–100)', '8')]:
            self.label_in(content, label, 14, 26)
            field = TextInput(text=default, multiline=False, input_filter='int' if default else None)
            content.add_widget(field)
            fields.append(field)
        self.label_in(content, 'Juego', 14, 26)
        game = Spinner(text=self.koth_default_game.upper(), values=('UN5', 'UN6'), size_hint_y=None, height=dp(44))
        content.add_widget(game)
        self.label_in(content, 'Estado de partida', 14, 26)
        state = Spinner(size_hint_y=None, height=dp(44))
        content.add_widget(state)
        variants = {'standard': 'Netplay', 'original': 'Netplay',
                    'transformed': 'Personajes transformados', 'audio20': 'Volumen al 20 %'}
        labels = {}

        def update_states(*_):
            labels.clear()
            labels.update((tr(variants[variant]), key) for key, (supported_game, variant) in KOTH_STATES.items()
                          if supported_game == game.text.lower())
            state.values = tuple(labels)
            state.text = state.values[0]

        game.bind(text=update_states)
        update_states()
        error_label = self.label_in(content, '', 14, 44)
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(content)
        popup = Popup(content=scroll, size_hint=(0.92, 0.85))
        self.set_text(popup, 'Crear evento casual', property_name='title')

        def submit():
            if self.busy:
                self.set_text(error_label, 'Espera a que termine la consulta actual.')
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
            self.manage_casual(source, session, {'name': name, 'target_points': points, 'max_participants': capacity,
                                                 'match_state': labels[state.text]})

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
                    and source == self.koth_url)
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
            choices = {item['id']: item for item in self.koth_events} if self.koth_events_url == source else {}
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
            transport = 'relay' if self.koth_network.text == 'Netplay' else 'zerotier'
            address = '0.0.0.0'
            if transport == 'zerotier':
                try:
                    address = validate_address(self.inputs['zt_address'].text.strip())
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

        config = {'directory': self.user_data_dir, 'pine_slot': slot,
                  'address': address, 'koth_transport': transport, 'transport': 'direct', 'role': 'koth', 'url': url,
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
                game, variant = event_match(result['event'], self.koth_default_game, event=event)
                config.update(game=game, variant=variant)
                self.launch_mobile_service(dict(config, koth_ticket=result['ticket']), return_to_game=False)

        self.run_job(lambda: enroll(url, event, name, store, netplay_session=session,
                                    address=address if transport == 'zerotier' else ''), show)

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
        self.reset_history()
        if self.collection_owner != self.appearance_owner() or not self.discord_verified:
            self.reset_collection()
        if self.discord_verified and self.sections.current == 'history':
            self.load_history(1)
        messages = {'restore': 'Sesión restaurada.', 'login': 'Sesión iniciada.', 'logout': 'Sesión cerrada.'}
        self.say(messages[operation] if ok else str(error))
        pending_source = self.pending_casual_source
        self.pending_casual_source = None
        if (pending_source and self.discord_verified and operation in ('restore', 'login')
                and pending_source == self.koth_url):
            self.create_casual()
        elif self.appearance_owner() and (self.sections.current == 'settings'
                                          or self.store_appearance.get(self.appearance_owner())):
            self.open_collection()

    def cancel_login(self):
        self.pending_casual_source = None
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
        self.tournament_status.text = (message if state.get('tournament') else None) or tr('Sin conexión.')
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

    def start_session(self, role, room_ip=None, room_tag=None):
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
        from host import prepare_files, zerotier_guest_state
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
            host_ip = resolve_zerotier_host(room_ip or self.host_ip.text, address) if role == 'guest' and transport == 'direct' else ''
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
                  'overlay': self.overlay.active, 'announce_zerotier': role == 'host' and transport == 'direct' and bool(address),
                  'stop_file': str(Path(self.user_data_dir) / 'host.stop')}
        def prepare():
            if role == 'guest' and transport == 'direct':
                variant, tag = zerotier_guest_state(game, host_ip, room_tag)
                return prepare_files(self.user_data_dir, game, variant=variant, expected_state_tag=tag)
            return prepare_files(self.user_data_dir, game, relay=transport == 'server')

        self.run_job(prepare, lambda _: self.launch_mobile_service(config))

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
                   {'phase': 'starting', 'role': config['role'], 'tournament': bool(config.get('fixture')),
                    'message': tr('Servicio iniciando…')}, private=True)
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
        self.reset_history()
        self.reset_collection()
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
        self.store_preview_worker.shutdown(wait=False, cancel_futures=True)
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

    def update_host_ip_hint(self, *_):
        self.zerotier_rooms_box.clear_widgets()
        try:
            prefix = zerotier_prefix(self.inputs['zt_address'].text)
        except ValueError:
            prefix = ''
        if prefix:
            self.set_text(self.ip_label, 'Último número de la IP del anfitrión · {prefix}', prefix=prefix)
        else:
            self.set_text(self.ip_label, 'IPv4 del anfitrión')
        self.host_ip.input_type = 'number' if prefix else 'text'
        self.host_ip.hint_text = '172' if prefix else '192.168.195.172'

    def refresh_zerotier_rooms(self):
        try:
            address = validate_address(self.inputs['zt_address'].text)
        except ValueError:
            self.say('Configura tu IPv4 de ZeroTier en Ajustes para buscar salas.')
            return

        def show(rooms):
            if address != self.inputs['zt_address'].text.strip():
                return
            self.zerotier_rooms_box.clear_widgets()
            if not rooms:
                self.label_in(self.zerotier_rooms_box, 'No se encontraron salas en tu red ZeroTier.', 14, 54)
            for room in rooms:
                self.button(self.zerotier_rooms_box, f"{room['nick']} · {room['game'].upper()} · {room['ip']}",
                            lambda room=room: self.join_zerotier_room(room))
                self.button(self.zerotier_rooms_box, 'Descargar estado de esta sala',
                            lambda room=room: self.export_zerotier_guest_state(room))
            self.say('Salas disponibles: {count}', count=len(rooms))

        session = self.account.session if self.discord_verified else None
        self.run_job(lambda: discover_zerotier_rooms(address, session), show)

    def join_zerotier_room(self, room):
        self.client_game.text = room['game']
        self.start_session('guest', room_ip=room['ip'], room_tag=room.get('tag'))

    def export_zerotier_guest_state(self, room=None):
        if platform != 'android':
            self.say('Guardar en Descargas está disponible en Android 10 o posterior.')
            return
        from downloads import download_state
        from host import zerotier_guest_state
        try:
            game = room['game'] if room else self.client_game.text
            host = room['ip'] if room else resolve_zerotier_host(self.host_ip.text, self.inputs['zt_address'].text)
        except ValueError as error:
            self.say(str(error))
            return

        def export():
            variant, tag = zerotier_guest_state(game, host, room.get('tag') if room else None)
            if not tag:
                raise ValueError(tr('El anfitrión todavía no anuncia el estado de la partida.'))
            return download_state(self.user_data_dir, game, variant=variant, expected_state_tag=tag)

        self.run_job(export, self.say)

    def open_client_role(self):
        if self.transport_mode(self.client_transport) == 'server' and not self.busy:
            self.refresh_rooms()

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
