"""Dedicated host/join window for experimental D.O.N online sessions."""
import json
import queue
import threading
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from appdata import DATA_DIR, write_json
from don_online import OnlineSession, manifest_for, make_package, publish_profile
from don_setup import DonSetupDialog, latest_state_directory
from multiplayer_client import DonRoomClient

ROOT = Path(__file__).resolve().parent


class DonRoomsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app, self.session, self.busy, self.closing = app, None, False, False
        self.messages = queue.Queue()
        self.title('D.O.N · salas online experimentales')
        self.transient(app)
        self.resizable(True, True)
        self.minsize(800, 690)
        # Modal within this launcher: the Naruto path must not take PINE while
        # the D.O.N session owns it. All network and PINE work stays off Tk.
        self.grab_set()
        saved = {}
        try:
            saved = json.loads((DATA_DIR/'don-online.json').read_text())
        except (OSError, ValueError):
            pass
        source_profiles = ROOT/'build/don/profiles'
        self.publish_root = source_profiles if source_profiles.is_dir() else DATA_DIR/'don/profiles'
        initial = {'role': 'host', 'players': '2', 'room_id': '',
                   'url': app.v['hill_url'].get() or 'https://narutimateonline.sytes.net',
                   'state_dir': app.cfg().get('state_dir') or latest_state_directory(), 'pine_slot': '28011', 'port': '47400'}
        for key in initial:
            if isinstance(saved.get(key), str):
                initial[key] = saved[key]
        self.v = {k: tk.StringVar(value=value) for k, value in initial.items()}
        self.status = tk.StringVar(value='Crea una sala o introduce el código de la sala del host.')
        box = ttk.Frame(self, padding=18)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text='Battle Stadium D.O.N · Online experimental', font=('', 15, 'bold')).pack(anchor='w')
        ttk.Label(box, text='Usa D.O.N abierto en PCSX2. Django descarga el estado inicial; ZeroTier conecta los mandos.\n'
                            'La sincronía del combate todavía no está certificada.', wraplength=760).pack(anchor='w', pady=(5, 12))
        self.tabs = ttk.Notebook(box)
        self.tabs.pack(fill='x', pady=(0, 10))
        main = ttk.Frame(self.tabs, padding=10)
        configuration = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(main, text='Crear sala / Unirme')
        self.tabs.add(configuration, text='PCSX2 y administración')
        role = ttk.Frame(main)
        role.pack(fill='x')
        for text, value in [('Host · crear sala', 'host'), ('Invitado · unirme', 'guest')]:
            ttk.Radiobutton(role, text=text, variable=self.v['role'], value=value).pack(side='left', padx=(0, 24))
        server = ttk.Frame(main)
        server.pack(fill='x', pady=(10, 4))
        ttk.Label(server, text='Servidor Django').pack(side='left', padx=(0, 10))
        ttk.Entry(server, textvariable=self.v['url']).pack(side='left', fill='x', expand=True)
        ttk.Label(main, text='Sala libre con tu cuenta del launcher. No requiere torneo ni inscripción.').pack(anchor='w')
        options = ttk.Frame(main)
        options.pack(fill='x', pady=8)
        ttk.Label(options, text='Jugadores (host)').pack(side='left')
        ttk.Combobox(options, textvariable=self.v['players'], values=('2', '3', '4'), state='readonly', width=4).pack(side='left', padx=(8, 24))
        ttk.Label(options, text='Código de sala').pack(side='left')
        ttk.Entry(options, textvariable=self.v['room_id']).pack(side='left', padx=(8, 0), fill='x', expand=True)
        self.get_address = app._zerotier_picker(main, app.v['hill_address'].get() or app.v['zerotier_address'].get())
        settings = ttk.LabelFrame(configuration, text='Instancia de PCSX2 abierta', padding=8)
        settings.pack(fill='x', pady=10)
        self._path(settings, 'Carpeta de estados de PCSX2', 'state_dir')
        ports = ttk.Frame(settings)
        ports.pack(fill='x', pady=4)
        for label, key in [('Ranura PINE', 'pine_slot'), ('Puerto UDP de ZeroTier', 'port')]:
            ttk.Label(ports, text=label).pack(side='left', padx=(0, 6))
            ttk.Entry(ports, textvariable=self.v[key], width=8).pack(side='left', padx=(0, 20))
        admin = ttk.LabelFrame(configuration, text='Administración de estados compartidos', padding=8)
        admin.pack(fill='x', pady=8)
        self.prepare = ttk.Button(admin, text='Preparar otro estado inicial…', command=self.prepare_state)
        self.prepare.pack(anchor='w', pady=4)
        self.publish = ttk.Button(admin, text='Publicar estados de 2, 3 y 4 jugadores en Django…', command=self.publish_states)
        self.publish.pack(anchor='w', pady=4)
        ttk.Label(admin, text='Solo un administrador publica los perfiles una vez. Host e invitados los descargan automáticamente.',
                  wraplength=720).pack(anchor='w')
        ttk.Label(settings, text='Abre la ISO, activa PINE y el Multitap del puerto 1. Los invitados descargan el perfil desde Django.',
                  wraplength=740).pack(anchor='w')
        actions = ttk.Frame(box)
        actions.pack(fill='x', pady=(0, 8))
        self.connect = ttk.Button(actions, text='Crear sala / Unirme', command=self.connect_room)
        self.connect.pack(side='left')
        self.play = ttk.Button(actions, text='Iniciar partida · host', state='disabled', command=self.start_match)
        self.play.pack(side='left', padx=8)
        self.end = ttk.Button(actions, text='Detener / Salir', state='disabled', command=self.stop)
        self.end.pack(side='left')
        ttk.Button(actions, text='Copiar código', command=self.copy_code).pack(side='right')
        self.roster = ttk.Treeview(box, columns=('player', 'address', 'state'), show='headings', height=4)
        for key, label, width in [('player', 'Puesto y jugador', 220), ('address', 'Dirección ZeroTier', 200), ('state', 'Estado', 160)]:
            self.roster.heading(key, text=label)
            self.roster.column(key, width=width)
        self.roster.pack(fill='both', expand=True)
        ttk.Label(box, textvariable=self.status, wraplength=760).pack(fill='x', pady=(8, 0))
        self.v['role'].trace_add('write', lambda *_: self.connect.configure(
            text='Crear sala' if self.v['role'].get() == 'host' else 'Unirme a la sala'))
        self.connect.configure(text='Crear sala' if self.v['role'].get() == 'host' else 'Unirme a la sala')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Destroy>', self.destroyed, add='+')
        self.after(100, self.poll)

    def _path(self, parent, label, key):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=label, width=30).pack(side='left')
        ttk.Entry(row, textvariable=self.v[key]).pack(side='left', fill='x', expand=True)
        def browse():
            value = filedialog.askdirectory(parent=self)
            if value:
                self.v[key].set(value)
        ttk.Button(row, text='Examinar…', command=browse).pack(side='right', padx=(6, 0))

    def connect_room(self):
        if self.busy or self.app.backend.running or getattr(self.app, '_koth_pending', False):
            return
        identity = self.app.backend.session
        if not identity:
            self.status.set('Inicia sesión con Discord en el launcher antes de crear o unirte.')
            return
        config = {k: value.get().strip() for k, value in self.v.items()}
        try:
            config.update(pine_slot=int(config['pine_slot']), port=int(config['port']), players=int(config['players']),
                          address=self.get_address())
            if config['role'] not in ('host', 'guest') or config['players'] not in (2, 3, 4):
                raise ValueError('Selecciona host/invitado y una cantidad de 2 a 4 jugadores.')
            if not 1 <= config['pine_slot'] <= 65535 or not 1024 <= config['port'] <= 65533:
                raise ValueError('Ranura PINE o puerto UDP fuera de rango.')
            import ipaddress
            address = ipaddress.IPv4Address(config['address'])
            if (not address.is_private or address.is_unspecified or address.is_loopback or address.is_multicast
                    or address.is_reserved or address.is_link_local):
                raise ValueError('Selecciona tu IPv4 privada de ZeroTier.')
            if not Path(config['state_dir']).is_dir():
                raise ValueError('Selecciona la carpeta de estados de la instancia abierta de PCSX2.')
            if config['role'] == 'guest':
                from uuid import UUID
                UUID(config['room_id'])
            write_json(DATA_DIR/'don-online.json', {k: str(config[k]) for k in self.v})
        except (ValueError, OSError) as error:
            self.status.set(str(error))
            return
        config['cache_dir'] = str(DATA_DIR)
        self.busy = True
        self.app._set_buttons(True)
        self.connect.configure(state='disabled')
        self.prepare.configure(state='disabled')
        self.publish.configure(state='disabled')
        self.end.configure(state='normal')
        self.status.set('Conectando tu cuenta y preparando la sala libre…')
        self.pending_stop = threading.Event()
        def work():
            try:
                client = DonRoomClient.authenticate(config['url'], identity)
                if self.pending_stop.is_set():
                    self.messages.put(('done', 'Conexión cancelada.'))
                    return
                session = OnlineSession(client, config, self.messages)
                self.session = session
                if self.pending_stop.is_set():
                    session.stop()
                session.run()
            except Exception as error:
                self.messages.put(('error', str(error)))
                self.messages.put(('done', 'No se pudo conectar la sala.'))
        threading.Thread(target=work, daemon=False).start()

    def prepare_state(self):
        if self.busy:
            return
        profile_root = self.publish_root
        child = DonSetupDialog(self, adapter_path=profile_root.parent/'adapter.json', profiles_dir=profile_root)
        child.port.set(self.v['pine_slot'].get())
        child.directory.set(self.v['state_dir'].get())
        child.wait_visibility()
        child.grab_set()
        child.bind('<Destroy>', lambda e: self.grab_set() if e.widget == child and self.winfo_exists() else None)

    def publish_states(self):
        if self.busy:
            return
        identity, url = self.app.backend.session, self.v['url'].get().strip()
        if not identity:
            self.status.set('Inicia sesión con la cuenta administradora del launcher.')
            return
        folder = filedialog.askdirectory(parent=self, title='Perfiles preparados de 2, 3 y 4 jugadores',
                                         initialdir=self.publish_root if self.publish_root.is_dir() else Path.home())
        if not folder:
            return
        self.publish_root = Path(folder)
        self.busy = True
        self.pending_stop = threading.Event()
        self.app._set_buttons(True)
        for button in (self.connect, self.prepare, self.publish):
            button.configure(state='disabled')
        self.end.configure(state='normal')
        self.status.set('Verificando la cuenta administradora y los perfiles…')
        def work():
            try:
                client = DonRoomClient.authenticate(url, identity)
                if not client.can_publish:
                    raise ValueError('Solo la cuenta administradora puede publicar los estados iniciales.')
                selected = {n: manifest_for(folder, n)[0] for n in (2, 3, 4)}
                with tempfile.TemporaryDirectory(prefix='don-publish-', dir=DATA_DIR) as temporary:
                    for n, profile in selected.items():
                        if self.pending_stop.is_set():
                            break
                        package = make_package(profile, Path(temporary)/f'{n}p.zip')
                        publish_profile(client, n, package)
                        self.messages.put(('log', f'Estado inicial de {n} jugadores publicado en Django.'))
            except Exception as error:
                self.messages.put(('error', str(error)))
            finally:
                self.messages.put(('done', 'Publicación terminada.'))
        threading.Thread(target=work, daemon=False).start()

    def start_match(self):
        if self.session:
            self.session.start_match()

    def copy_code(self):
        self.clipboard_clear()
        self.clipboard_append(self.v['room_id'].get())

    def stop(self):
        if self.busy:
            self.pending_stop.set()
            if self.session:
                self.session.stop()
            self.play.configure(state='disabled')
            self.status.set('Deteniendo la sala y devolviendo los controles…')

    def close(self):
        if self.busy:
            self.closing = True
            self.stop()
        else:
            self.destroy()

    def destroyed(self, event):
        if event.widget == self:
            if hasattr(self, 'pending_stop'):
                self.pending_stop.set()
            if self.session:
                self.session.stop()

    def poll(self):
        if not self.winfo_exists():
            return
        while True:
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == 'room':
                self.v['room_id'].set(value['id'])
                self.v['players'].set(str(value['capacity']))
                self.roster.delete(*self.roster.get_children())
                for player in value['players']:
                    self.roster.insert('', 'end', values=(f"P{player['slot']+1} · {player['name']}",
                        player['address'] or '—', 'Listo' if player['ready'] else 'Preparando'))
                self.play.configure(state='normal' if self.busy and value['slot'] == 0 and value['can_start'] else 'disabled')
            elif kind == 'progress':
                self.status.set(f"Online experimental · fotograma {value['frame']} · RTT {value['rtt']} ms · "
                                'verificación de entradas; sincronía de combate no certificada.')
            elif kind == 'done':
                self.busy, self.session = False, None
                self.connect.configure(state='normal')
                self.prepare.configure(state='normal')
                self.publish.configure(state='normal')
                self.play.configure(state='disabled')
                self.end.configure(state='disabled')
                self.app._set_buttons(self.app.backend.running)
                if self.closing:
                    self.destroy()
                    return
                self.app._log('D.O.N: '+value, 'info')
            else:
                self.status.set(value)
                self.app._log('D.O.N: '+value, 'error' if kind == 'error' else 'info')
        self.after(100, self.poll)
