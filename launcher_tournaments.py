"""Desktop tournament registration and round-by-round bracket viewer."""
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk
import webbrowser

from i18n import tr
from koth_client import (TOURNAMENT_FORMATS, assigned_fixture, join_tournament, scheduled_tournaments,
                         site_url, tournament_bracket)
from launcher_theme import MUTED, PANEL, TEXT, RoundFrame


def fixture_slot(row, slot):
    name = row.get(f'player{slot}__name')
    if name:
        return name
    source = row.get(f'source{slot}__number')
    if source:
        key = 'bracket.loser' if row[f'source{slot}_loser'] else 'bracket.winner'
        return tr(key, number=source)
    return '—'


class TournamentPanel(RoundFrame):
    def __init__(self, parent, app):
        super().__init__(parent, radius=20, padx=16, pady=14, grow=True)
        self.app = app
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.bind('<Destroy>', self._destroy, add='+')
        self.events = {}
        self.url = ''
        self.generation = 0
        self.joining = False
        self.confirmed = {}
        self.fixture_rows = {}
        self.checking_fixture = False
        bar = tk.Frame(self.inner, bg=PANEL)
        bar.pack(fill='x')
        tk.Label(bar, text=tr('nav.tournaments'), bg=PANEL, fg=TEXT,
                 font=('Segoe UI', 14, 'bold')).pack(side='left')
        ttk.Button(bar, text=tr('koth.refresh'), command=self.refresh).pack(side='right')
        self.listing = self.table(('#0', 'format', 'date', 'players', 'status'),
                                  ('koth.event', 'tourney.format', 'tourney.date', 'koth.players', 'koth.state'), 5)
        self.listing.bind('<<TreeviewSelect>>', self.select)
        buttons = tk.Frame(self.inner, bg=PANEL)
        buttons.pack(fill='x', pady=6)
        self.join = ttk.Button(buttons, text=tr('tourney.join'), command=self.enroll, state='disabled')
        self.join.pack(side='left')
        self.web = ttk.Button(buttons, text=tr('bracket.public'), command=self.public_page, state='disabled')
        self.web.pack(side='left', padx=8)
        self.notice = tk.Label(self.inner, bg=PANEL, fg=MUTED, anchor='w', wraplength=650)
        self.notice.pack(fill='x')
        tk.Label(self.inner, text=tr('bracket.title'), bg=PANEL, fg=TEXT, anchor='w',
                 font=('Segoe UI', 11, 'bold')).pack(fill='x', pady=(10, 2))
        self.bracket = self.table(('#0', 'p1', 'score', 'p2', 'status'),
                                  ('bracket.round', 'bracket.p1', 'bracket.score', 'bracket.p2', 'koth.state'), 8,
                                  expand=True)

        self.connect = ttk.Button(buttons, text=tr('bracket.connect'), command=self.connect_selected,
                                  state='disabled')
        self.connect.pack(side='left')
        self.bracket.bind('<<TreeviewSelect>>', self.sync_connect)

    def sync_connect(self, _event=None):
        selected = self.bracket.selection()
        row = self.fixture_rows.get(selected[0], {}) if selected else {}
        enabled = (row.get('status') == 'ready' and not self.checking_fixture and not self.app.backend.running
                   and not self.app._koth_pending and self.app._after_sync is None and self.app._after_allow is None)
        self.connect.configure(state='normal' if enabled else 'disabled')

    def connect_selected(self):
        selected = self.bracket.selection()
        row = self.fixture_rows.get(selected[0]) if selected else None
        event = self.selected()
        if not row or row['status'] != 'ready' or not event or self.checking_fixture:
            return
        session = self.app.backend.session
        if not session:
            self.notice.configure(text=tr('bracket.login'))
            return
        url = self.url
        self.checking_fixture = True
        self.sync_connect()
        def checked(fixture, error):
            self.checking_fixture = False
            self.sync_connect()
            if (self.app.section.get() != 'tournaments' or self.selected() != event or self.url != url
                    or self.app.backend.session != session or self.bracket.selection() != selected
                    or self.fixture_rows.get(selected[0]) != row):
                return
            if error or not fixture:
                self.notice.configure(text=error or tr('bracket.unassigned'))
                return
            self.app.zerotier(fixture=fixture)
        self.run(lambda: assigned_fixture(url, session, event['id'], row), checked)

    def table(self, columns, titles, height, expand=False):
        frame = ttk.Frame(self.inner)
        frame.pack(fill='both' if expand else 'x', expand=expand, pady=4)
        tree = ttk.Treeview(frame, columns=columns[1:], height=height, selectmode='browse')
        for key, title in zip(columns, titles):
            tree.heading(key, text=tr(title))
            tree.column(key, width=150 if key == '#0' else 90, minwidth=35)
        scroll = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        tree.pack(fill='both', expand=True)
        return tree

    def _destroy(self, event):
        if event.widget is self:
            self.pool.shutdown(wait=False, cancel_futures=True)

    def run(self, work, done):
        future = self.pool.submit(work)
        def poll():
            if not future.done():
                self.after(75, poll)
                return
            try:
                value = future.result()
            except Exception as error:
                done(None, str(error))
            else:
                done(value, '')
        self.after(75, poll)

    def selected(self):
        selected = self.listing.selection()
        return self.events.get(selected[0]) if selected else None

    def refresh(self):
        self.generation += 1
        generation = self.generation
        url = self.app.v['hill_url'].get().strip()
        if self.url != url:
            self.events.clear()
            self.listing.delete(*self.listing.get_children())
            self.select()
        self.url = url
        self.notice.configure(text=tr('koth.loading'))
        def loaded(events, error):
            if generation != self.generation:
                return
            if error:
                self.notice.configure(text=error)
                return
            old = self.listing.selection()
            self.events = {str(e['id']): e for e in events}
            self.listing.delete(*self.listing.get_children())
            for key, event in self.events.items():
                self.listing.insert('', 'end', iid=key, text=event['name'], values=(
                    TOURNAMENT_FORMATS[event['format']], event.get('event_date') or '—',
                    f"{event['enrolled']}/{event['max_participants']}", tr('bracket.' + event.get('status', 'draft'))))
            if events:
                self.listing.selection_set(old[0] if old and old[0] in self.events else str(events[0]['id']))
            else:
                self.select()
                self.notice.configure(text=tr('tourney.empty_list'))
        self.run(lambda: scheduled_tournaments(url, all_statuses=True), loaded)

    def select(self, _event=None):
        event = self.selected()
        self.fixture_rows.clear()
        self.sync_connect()
        self.bracket.delete(*self.bracket.get_children())
        self.web.configure(state='normal' if event else 'disabled')
        enabled = event and event.get('status', 'draft') == 'draft' and not self.joining
        self.join.configure(state='normal' if enabled else 'disabled')
        if not event:
            return
        generation, url = self.generation, self.url
        session = self.app.backend.session
        key = (url, event['id'], session)
        participant = self.confirmed.get(key)
        confirmed = tr('tourney.confirmed', name=event['name'], id=participant) if participant else ''
        self.notice.configure(text=confirmed or tr('koth.loading'))
        def loaded(data, error):
            if generation != self.generation or self.selected() != event:
                return
            self.bracket.delete(*self.bracket.get_children())
            if error:
                self.notice.configure(text=' '.join(filter(None, (confirmed, error))))
                return
            groups = {}
            for row in data['fixtures']:
                group = row['stage'], row['round_number']
                if group not in groups:
                    title = tr('bracket.stage_round', stage=tr('bracket.' + group[0]), number=group[1])
                    groups[group] = self.bracket.insert('', 'end', text=title, open=True)
                item = self.bracket.insert(groups[group], 'end', text=f"#{row['number']}", values=(
                    fixture_slot(row, 1), f"{row['p1_wins']} – {row['p2_wins']}", fixture_slot(row, 2),
                    tr('bracket.' + row['status'])))
                self.fixture_rows[item] = row
            self.notice.configure(text=' '.join(filter(None, (confirmed, '' if groups else tr('bracket.pending')))))
        self.run(lambda: tournament_bracket(url, event['id']), loaded)

    def enroll(self):
        event = self.selected()
        if not event or self.joining:
            return
        session = self.app.backend.session
        if not session:
            self.notice.configure(text=tr('tourney.login'))
            return
        self.joining = True
        url = self.url
        self.join.configure(state='disabled')
        def finished(participant, error):
            self.joining = False
            if error:
                self.join.configure(state='normal' if self.selected() and self.selected().get('status', 'draft') == 'draft' else 'disabled')
                self.notice.configure(text=error)
                return
            self.confirmed[url, event['id'], session] = participant
            self.refresh()
        self.run(lambda: join_tournament(url, session, event['id']), finished)

    def public_page(self):
        event = self.selected()
        if event:
            webbrowser.open(f"{site_url(self.url)}/torneos/{int(event['id'])}/publico/")
