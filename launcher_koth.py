"""KOTH event browser and live score board for the Tk launcher."""
import threading
import time
import tkinter as tk
from tkinter import ttk

from i18n import tr
from koth_client import DEFAULT_URL, get_event, list_events
from launcher_theme import ACCENT, BORDER, DIM, GREEN, MUTED, PANEL, RED, TEXT, RoundFrame


class KothPanel(RoundFrame):
    def __init__(self, parent, app):
        super().__init__(parent, radius=20, padx=16, pady=14, grow=True)
        self.app, self.events = app, {}
        ttk.Style(self).configure('Koth.Treeview', rowheight=30)
        self.loaded_url, self.last_event = None, None
        self.busy, self.next_poll = False, 0
        if not app.v['hill_url'].get().strip():
            app.v['hill_url'].set(DEFAULT_URL)
        inner = self.inner
        self.title = tk.Label(inner, text=tr('koth.events'), bg=PANEL, fg=TEXT,
                              font=('Segoe UI', 14, 'bold'), anchor='w')
        self.title.pack(fill='x')
        self.status = tk.Label(inner, text='', bg=PANEL, fg=MUTED, anchor='w', wraplength=620,
                               justify='left', font=('Segoe UI', 9))
        self.status.pack(fill='x', pady=(2, 8))
        server = tk.Frame(inner, bg=PANEL)
        self.server_row = server
        server.pack(fill='x', pady=(0, 10))
        self.url_entry = ttk.Entry(server, textvariable=app.v['hill_url'])
        self.url_entry.pack(side='left', fill='x', expand=True)
        ttk.Button(server, text=tr('koth.refresh'), command=self.refresh).pack(side='right', padx=(8, 0))

        self.events_frame = tk.Frame(inner, bg=PANEL)
        self.events_frame.pack(fill='both', expand=True)
        scrollbar = ttk.Scrollbar(self.events_frame, orient='vertical')
        self.tree = ttk.Treeview(self.events_frame, columns=('state', 'players', 'goal'), style='Koth.Treeview',
                                 show='tree headings', selectmode='browse', height=7,
                                 yscrollcommand=scrollbar.set)
        self.tree.heading('#0', text=tr('koth.event'))
        self.tree.column('#0', width=240, minwidth=140)
        for key, label, width in [('state', 'koth.state', 110), ('players', 'koth.players', 85), ('goal', 'koth.goal', 75)]:
            self.tree.heading(key, text=tr(label))
            self.tree.column(key, width=width, minwidth=60, stretch=False)
        scrollbar.configure(command=self.tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        self.tree.bind('<Double-1>', lambda event: app.start() if not app.backend.running else None)

        self.preview = tk.Label(inner, text=tr('koth.pick'), bg=PANEL, fg=MUTED, anchor='w',
                                wraplength=620, justify='left', font=('Segoe UI', 9))
        self.preview.pack(fill='x', pady=(8, 0))
        self.board = tk.Frame(inner, bg=PANEL)
        tk.Label(self.board, text=tr('koth.current'), bg=PANEL, fg=TEXT,
                 font=('Segoe UI', 10, 'bold'), anchor='w').pack(fill='x', pady=(0, 8))
        cards = tk.Frame(self.board, bg=PANEL)
        cards.pack(fill='x', pady=(0, 10))
        self.names, self.points = [], []
        for index, title in enumerate(('koth.king', 'koth.challenger', 'koth.next')):
            cards.columnconfigure(index, weight=1, uniform='players')
            card = tk.Frame(cards, bg='#111b29', highlightbackground=ACCENT if index == 2 else BORDER,
                             highlightthickness=1, padx=10, pady=10)
            card.grid(row=0, column=index, sticky='nsew', padx=(0 if index == 0 else 6, 0))
            tk.Label(card, text=tr(title), bg='#111b29', fg=GREEN if index == 2 else MUTED,
                     font=('Segoe UI', 9, 'bold')).pack(anchor='w')
            name = tk.Label(card, text='—', bg='#111b29', fg=TEXT, font=('Segoe UI', 12, 'bold'),
                            wraplength=160, anchor='w', justify='left')
            name.pack(fill='x', pady=(8, 4))
            points = tk.Label(card, text='—', bg='#111b29', fg=GREEN, font=('Segoe UI', 23, 'bold'), anchor='w')
            points.pack(fill='x')
            self.names.append(name)
            self.points.append(points)
        self.goal = tk.Label(self.board, text='', bg=PANEL, fg=MUTED, anchor='w')
        self.goal.pack(fill='x', pady=(0, 8))
        tk.Label(self.board, text=tr('koth.queue'), bg=PANEL, fg=TEXT,
                 font=('Segoe UI', 10, 'bold'), anchor='w').pack(fill='x', pady=(0, 5))
        wrap = tk.Frame(self.board, bg=PANEL)
        wrap.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(wrap, orient='vertical')
        self.queue = ttk.Treeview(wrap, columns=('points', 'turn'), show='tree headings', style='Koth.Treeview',
                                  selectmode='none', height=4, yscrollcommand=scroll.set)
        self.queue.heading('#0', text=tr('koth.player'))
        self.queue.column('#0', width=270, minwidth=160)
        for key, label, width in [('points', 'koth.points', 80), ('turn', 'koth.turn', 160)]:
            self.queue.heading(key, text=tr(label))
            self.queue.column(key, width=width, minwidth=65, stretch=False)
        scroll.configure(command=self.queue.yview)
        scroll.pack(side='right', fill='y')
        self.queue.pack(fill='both', expand=True)
        self.display(getattr(app, 'koth_live_event', None))

    def selected_event(self):
        if self.loaded_url != self.app.v['hill_url'].get().strip():
            return None
        selected = self.tree.selection()
        return self.events.get(selected[0]) if selected else None

    def _select(self, event=None):
        selected = self.selected_event()
        if selected:
            self.app.v['hill_event_id'].set(str(selected['id']))
            self.app.koth_hint.configure(text=selected['name'])
            players = selected.get('current_match') or {}
            names = ' vs '.join(players[slot]['name'] for slot in ('player1', 'player2') if players.get(slot))
            self.preview.configure(text=names or tr('koth.pick'))

    def refresh(self):
        self.next_poll = 0
        self.tick()

    def tick(self):
        if self.busy or time.monotonic() < self.next_poll:
            return
        url = self.app.v['hill_url'].get().strip()
        if not url:
            return
        self.busy, self.next_poll = True, time.monotonic()+3
        live = getattr(self.app, 'koth_live_event', None)
        live_id = live.get('id') if live else None

        def work():
            try:
                events = list_events(url)
                detail = next((event for event in events if event['id'] == live_id), None)
                if live_id and detail is None:
                    detail = get_event(url, live_id)
                result = (events, detail, '')
            except Exception as error:
                result = ([], None, str(error))
            self.app.backend.q.put(('koth_events', self, url, *result))

        threading.Thread(target=work, daemon=True).start()

    def update_events(self, url, events, detail, error):
        self.busy = False
        if url != self.app.v['hill_url'].get().strip():
            self.next_poll = 0
            return
        if error:
            self.status.configure(text=error, fg=RED)
            return
        self.events = {str(event['id']): event for event in events}
        self.loaded_url = url
        wanted = self.app.v['hill_event_id'].get()
        old_ids = set(self.tree.get_children())
        for key in old_ids-self.events.keys():
            self.tree.delete(key)
        for index, (key, event) in enumerate(self.events.items()):
            values = (tr('koth.'+event['status']), f"{len(event['queue'])}/{event['max_participants']}", event['target_points'])
            if key in old_ids:
                self.tree.item(key, text=event['name'], values=values)
            else:
                self.tree.insert('', 'end', iid=key, text=event['name'], values=values)
            self.tree.move(key, '', index)
        if wanted in self.events and not self.tree.selection():
            self.tree.selection_set(wanted)
        if detail:
            self.app.koth_live_event = detail
        self.display(detail or getattr(self.app, 'koth_live_event', None))
        if not self._connected():
            self.status.configure(text=tr('koth.event_count', n=len(events)), fg=MUTED)
        self._select()

    def _connected(self):
        return (self.app.backend.running and self.app.backend.session_role == 'hill') or getattr(self.app, '_koth_pending', False)

    def display(self, event=None, role=None, reason=None):
        connected = self._connected()
        if connected and role is None and reason is None:
            state = getattr(self.app, 'koth_live_state', {})
            if event and (state.get('event') or {}).get('id') == event['id']:
                role, reason = state.get('role'), state.get('reason')
        self.url_entry.configure(state='readonly' if connected else 'normal')
        if connected:
            self.server_row.pack_forget()
            self.events_frame.pack_forget()
            self.preview.pack_forget()
            self.board.pack(fill='both', expand=True)
        else:
            self.board.pack_forget()
            self.events_frame.pack(fill='both', expand=True)
            self.server_row.pack(fill='x', pady=(0, 10), before=self.events_frame)
            self.preview.pack(fill='x', pady=(8, 0))
        self.title.configure(text=event['name'] if connected and event else tr('koth.events'))
        if role is not None or reason:
            label = tr('koth.role.'+role) if role else tr('koth.waiting')
            self.status.configure(text=f'{label} · {reason}' if reason else label, fg=MUTED)
        elif connected and not event:
            self.status.configure(text=tr('koth.loading'), fg=MUTED)
        if not event:
            for label in self.names+self.points:
                label.configure(text='—')
            self.queue.delete(*self.queue.get_children())
            self.goal.configure(text='')
            self.last_event = None
            return
        if event == self.last_event:
            return
        self.last_event = event
        match = event.get('current_match') or {}
        players = [match.get('player1'), match.get('player2'), event.get('next_player')]
        if event['status'] == 'finished':
            players = [event.get('champion'), None, None]
            self.status.configure(text=tr('koth.finished'), fg=GREEN)
        for index, player in enumerate(players):
            self.names[index].configure(text=player['name'] if player else '—')
            self.points[index].configure(text=str(player['points']) if player else '—')
        self.goal.configure(text=tr('koth.target', n=event['target_points']))
        for key in self.queue.get_children():
            self.queue.delete(key)
        for index, player in enumerate(event.get('queue', [])):
            turn = ('koth.finished' if event['status'] == 'finished' else
                    'koth.playing' if match and index < 2 else 'koth.next' if (match and index == 2) else 'koth.waiting')
            self.queue.insert('', 'end', text=f"{index+1}. {player['name']}",
                               values=(player['points'], tr(turn)))
