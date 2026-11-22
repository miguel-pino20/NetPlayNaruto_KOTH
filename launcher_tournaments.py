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
        self.bracket_request = 0
        self.poll_bracket = None
        self.joining = False
        self.confirmed = {}
        self.checking_fixture = False
        self.inner.columnconfigure(0, weight=1)
        self.inner.rowconfigure(1, weight=1)
        self.inner.rowconfigure(5, weight=3)
        # The rooms view uses tall rows for avatars. Tournament rows only contain text.
        from tkinter import font
        line = font.nametofont('TkDefaultFont').metrics('linespace')
        ttk.Style(self).configure('Tournament.Treeview', rowheight=line + 8)
        bar = tk.Frame(self.inner, bg=PANEL)
        bar.grid(row=0, column=0, sticky='ew')
        tk.Label(bar, text=tr('nav.tournaments'), bg=PANEL, fg=TEXT,
                 font=('Segoe UI', 14, 'bold')).pack(side='left')
        ttk.Button(bar, text=tr('koth.refresh'), command=self.refresh).pack(side='right')
        self.listing = self.table(('#0', 'format', 'date', 'players', 'status'),
                                  ('koth.event', 'tourney.format', 'tourney.date', 'koth.players', 'koth.state'), row=1)
        self.listing.bind('<<TreeviewSelect>>', self.select)
        buttons = tk.Frame(self.inner, bg=PANEL)
        buttons.grid(row=2, column=0, sticky='ew', pady=3)
        self.join = ttk.Button(buttons, text=tr('tourney.join'), command=self.enroll, state='disabled')
        self.join.pack(side='left')
        self.web = ttk.Button(buttons, text=tr('bracket.public'), command=self.public_page, state='disabled')
        self.web.pack(side='left', padx=8)
        self.notice = tk.Label(self.inner, bg=PANEL, fg=MUTED, anchor='w', wraplength=650)
        self.notice.grid(row=3, column=0, sticky='ew')
        self.inner.bind('<Configure>', lambda e: self.notice.configure(wraplength=max(1, e.width)), add='+')
        tk.Label(self.inner, text=tr('bracket.title'), bg=PANEL, fg=TEXT, anchor='w',
                 font=('Segoe UI', 11, 'bold')).grid(row=4, column=0, sticky='ew', pady=(4, 2))
        self.bracket = self.table(('#0', 'p1', 'score', 'p2', 'status'),
                                  ('bracket.round', 'bracket.p1', 'bracket.score', 'bracket.p2', 'koth.state'), row=5)

        self.connect = ttk.Button(buttons, text=tr('bracket.connect'), command=self.connect_my_match,
                                  state='disabled')
        self.connect.pack(side='left')

    def sync_connect(self):
        event = self.selected()
        enabled = (event and event.get('status') == 'running' and not self.checking_fixture
                   and not self.app.backend.running and not self.app._koth_pending
                   and self.app._after_sync is None and self.app._after_allow is None)
        self.connect.configure(state='normal' if enabled else 'disabled')

    def connect_my_match(self):
        event = self.selected()
        if not event or event.get('status') != 'running' or self.checking_fixture:
            return
        session = self.app.backend.session
        if not session:
            self.notice.configure(text=tr('bracket.login'))
            return
        url = self.url
        self.app._log(tr('bracket.lookup'), 'info')
        self.checking_fixture = True
        self.sync_connect()
        def checked(fixture, error):
            self.checking_fixture = False
            self.sync_connect()
            if (self.app.section.get() != 'tournaments' or self.selected() != event or self.url != url
                    or self.app.backend.session != session):
                return
            if error or not fixture:
                self.notice.configure(text=error or tr('bracket.unassigned'))
                self.app._log(error or tr('bracket.unassigned'), 'error' if error else 'info')
                return
            self.app.zerotier(fixture=fixture)
        self.run(lambda: assigned_fixture(url, session, event['id']), checked)

    def table(self, columns, titles, row):
        frame = ttk.Frame(self.inner)
        frame.grid(row=row, column=0, sticky='nsew', pady=2)
        tree = ttk.Treeview(frame, columns=columns[1:], height=1, selectmode='browse', style='Tournament.Treeview')
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
        self.bracket_request += 1
        request = self.bracket_request
        if self.poll_bracket:
            self.after_cancel(self.poll_bracket)
            self.poll_bracket = None
        event = self.selected()
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
        def current():
            return (request == self.bracket_request and generation == self.generation and self.selected() == event
                    and self.app.section.get() == 'tournaments')

        def fetch():
            self.poll_bracket = None
            if current():
                self.run(lambda: tournament_bracket(url, event['id']), loaded)

        def loaded(data, error):
            if not current():
                return
            status = event.get('status')
            if error:
                self.notice.configure(text=' '.join(filter(None, (confirmed, error))))
            else:
                status = data.get('status', status)
                for row in data['fixtures']:
                    group = f"{row['stage']}-{row['round_number']}"
                    if not self.bracket.exists(group):
                        title = tr('bracket.stage_round', stage=tr('bracket.' + row['stage']), number=row['round_number'])
                        self.bracket.insert('', 'end', iid=group, text=title, open=True)
                    key = str(row['number'])
                    values = (fixture_slot(row, 1), f"{row['p1_wins']} – {row['p2_wins']}", fixture_slot(row, 2),
                              tr('bracket.' + row['status']))
                    if self.bracket.exists(key):
                        self.bracket.item(key, values=values)
                    else:
                        self.bracket.insert(group, 'end', iid=key, text=f"#{key}", values=values)
                if status != event.get('status', 'draft'):
                    self.refresh()
                    return
                if self.notice.cget('text') == tr('koth.loading') or not self.notice.cget('text'):
                    self.notice.configure(text=' '.join(filter(None, (confirmed, '' if data['fixtures'] else tr('bracket.pending')))))
            if status == 'running':
                self.poll_bracket = self.after(5000, fetch)
        fetch()

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
