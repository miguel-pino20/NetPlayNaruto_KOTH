"""Small setup dialog for capturing a 2/3/4-player D.O.N initial state."""
import configparser
import json
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from don_core import DonCore, prepare_state
from don_profiles import create_profile
from pine import Pine


ROOT = Path(__file__).resolve().parent


def latest_state_directory(pine_slot=28011):
    for session in sorted((ROOT/'build/don').glob('pcsx2-test*/session.json'),
                          key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(session.read_text())
            if data.get('pine_slot') != pine_slot:
                continue
            cfg = configparser.ConfigParser(interpolation=None, strict=False)
            cfg.read(Path(data['data_path'])/'PCSX2/inis/PCSX2.ini')
            return cfg.get('Folders', 'Savestates')
        except (OSError, ValueError, KeyError, configparser.Error):
            continue
    if pine_slot == 28011:
        for data_root in (Path.home()/'.var/app/net.pcsx2.PCSX2/config/PCSX2',
                          Path.home()/'.config/PCSX2'):
            cfg = configparser.ConfigParser(interpolation=None, strict=False)
            if cfg.read(data_root/'inis/PCSX2.ini'):
                folder = Path(cfg.get('Folders', 'Savestates', fallback='sstates'))
                return str(folder if folder.is_absolute() else data_root/folder)
    return ''


class DonSetupDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('D.O.N · estado inicial')
        self.resizable(False, False)
        if parent.winfo_viewable():
            self.transient(parent)
        self.busy = False
        self.results = queue.Queue()
        self.players = tk.StringVar(value='')
        self.adapter = tk.StringVar(value=str(ROOT/'build/don/adapter.json'))
        self.directory = tk.StringVar(value=latest_state_directory())
        self.port = tk.StringVar(value='28011')
        self.port.trace_add('write', self.update_directory)
        self.status = tk.StringVar(value='Selecciona cuántos jugadores se conectarán.')
        box = ttk.Frame(self, padding=18)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text='D.O.N · preparar estado compartido', font=('', 13, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 12))
        ttk.Label(box, text='Jugadores que se conectarán').grid(row=1, column=0, sticky='w')
        self.count = ttk.Combobox(box, textvariable=self.players, values=('2', '3', '4'), state='readonly', width=8)
        self.count.grid(row=1, column=1, sticky='w', pady=6)
        ttk.Label(box, text='En «Organícense», deja esa cantidad de puestos en JUGADOR\n'
                            'y los restantes como CPU o desactivados. Reanuda PCSX2 antes de capturar.').grid(
            row=2, column=0, columnspan=3, sticky='w', pady=(3, 12))
        for row, label, variable, browse in (
            (3, 'Perfil experimental (adapter.json)', self.adapter, self.browse_adapter),
            (4, 'Carpeta de estados de esa instancia', self.directory, self.browse_directory),
        ):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=5)
            ttk.Entry(box, textvariable=variable, width=48).grid(row=row, column=1, sticky='ew')
            ttk.Button(box, text='Examinar…', command=browse).grid(row=row, column=2, padx=(6, 0))
        ttk.Label(box, text='Ranura PINE de PCSX2').grid(row=5, column=0, sticky='w', pady=5)
        ttk.Entry(box, textvariable=self.port, width=9).grid(row=5, column=1, sticky='w')
        ttk.Label(box, textvariable=self.status, wraplength=650).grid(row=6, column=0, columnspan=3,
                                                                   sticky='w', pady=14)
        self.capture = ttk.Button(box, text='Capturar estado inicial', command=self.save, state='disabled')
        self.capture.grid(row=7, column=0, sticky='w')
        ttk.Button(box, text='Cerrar', command=self.close).grid(row=7, column=2, sticky='e')
        ttk.Label(box, text='Preparación experimental. Todavía no inicia partidas online.').grid(
            row=8, column=0, columnspan=3, sticky='w', pady=(12, 0))
        self.players.trace_add('write', lambda *_: self.capture.configure(
            state='normal' if self.players.get() in ('2', '3', '4') and not self.busy else 'disabled'))
        self.protocol('WM_DELETE_WINDOW', self.close)

    def browse_adapter(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('Perfil del adaptador', '*.json')])
        if path:
            self.adapter.set(path)

    def update_directory(self, *_):
        try:
            folder = latest_state_directory(int(self.port.get()))
        except ValueError:
            return
        self.directory.set(folder)

    def browse_directory(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.directory.set(path)

    def save(self):
        if self.busy or self.players.get() not in ('2', '3', '4'):
            return
        try:
            port = int(self.port.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.status.set('Introduce una ranura PINE entre 1 y 65535.')
            return
        count, adapter, directory = int(self.players.get()), self.adapter.get(), self.directory.get()
        output = Path(adapter).resolve().parent/'profiles'/f'{count}p'/datetime.now().strftime('%Y%m%d-%H%M%S')
        self.busy = True
        self.count.configure(state='disabled')
        self.capture.configure(state='disabled')
        self.status.set('Capturando el estado de «Organícense» y comprobando la cantidad de jugadores…')

        def work():
            pine = Pine(port, timeout=3)
            try:
                metadata = json.loads(Path(adapter).read_text())
                pine.connect()
                core = DonCore(pine, metadata)
                version = pine.version()
                snapshot = prepare_state(core, directory, output/'DON-organicense.p2s', capacity=count)
                result = create_profile(snapshot['path'], metadata, count, version, output)
                self.results.put((True, result['manifest']))
            except Exception as error:
                self.results.put((False, str(error)))
            finally:
                pine.close()

        threading.Thread(target=work, daemon=False).start()
        self.after(100, self.poll)

    def poll(self):
        try:
            ok, result = self.results.get_nowait()
        except queue.Empty:
            self.after(100, self.poll)
            return
        self.busy = False
        self.count.configure(state='readonly')
        self.capture.configure(state='normal')
        self.status.set(('Estado y perfil preparados:\n' if ok else 'No se pudo preparar el estado:\n')+result)

    def close(self):
        if self.busy:
            self.status.set('Terminando la captura y devolviendo los controles al juego…')
        else:
            self.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    dialog = DonSetupDialog(root)
    dialog.bind('<Destroy>', lambda event: root.destroy() if event.widget == dialog else None)
    root.mainloop()
