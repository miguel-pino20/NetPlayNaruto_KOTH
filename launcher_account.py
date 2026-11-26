#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UN5 Netplay - janelas da conta (login com Discord e perfil). Usadas pelo launcher.py."""
from __future__ import annotations

import io
import re
import time
import tkinter as tk
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tkinter import messagebox, ttk
from urllib.request import HTTPSHandler, build_opener

from i18n import AUTO_LANG, LANGS, get_lang, tr
from discord_auth import AccountError, NoRedirect, account_game_nick, api_call, ssl_context
from koth_client import DEFAULT_URL
from launcher_theme import ACCENT, BG, BORDER, DIM, GREEN, PANEL, RED, TEXT, AvatarView, PillButton, RoundFrame, Segmented, Switch


class _Dialog(tk.Toplevel):
    def __init__(self, app, title, width=380):
        super().__init__(app)
        self.app, self.buttons = app, []
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)
        card = RoundFrame(self, radius=20, padx=20, pady=18, minwidth=width)
        card.pack(fill="both", expand=True, padx=14, pady=14)
        self.card, self.body = card, card.inner
        self.msg = tk.Label(self.body, text="", bg=PANEL, fg=DIM, font=("Segoe UI", 9), wraplength=width - 50,
                            justify="left", anchor="w")
        app.dialog = self
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())

    def preferences(self):
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(12, 0))
        tk.Label(row, text=tr("lang.label"), bg=PANEL, fg=TEXT).pack(side="left")
        codes = (AUTO_LANG, *LANGS)
        languages = ttk.Combobox(row, values=(tr("lang.auto"), *LANGS.values()), state="readonly", width=15)
        languages.current(codes.index(self.app.v["lang"].get()))
        languages.pack(side="right")

        def change_language(_event):
            self.app.v["lang"].set(codes[languages.current()])
            self.app._change_lang()

        languages.bind("<<ComboboxSelected>>", change_language)
        Switch(self.body, tr("pf.background"), self.app.v["show_background"],
               self.app._change_background).pack(anchor="w", pady=(6, 0))
        self.button(self.body, tr("zt.settings"), self.app.configure_zerotier).pack(fill="x", pady=(8, 0))

    def present(self):
        self.card.sync()
        self.update_idletasks()
        a = self.app
        x = a.winfo_x() + (a.winfo_width() - self.winfo_width()) // 2
        y = a.winfo_y() + (a.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def close(self):
        if self.app.dialog is self:
            self.app.dialog = None
        self.destroy()

    def button(self, parent, text, command, style="TButton"):
        b = PillButton(parent, text=text, command=command, style=style)
        self.buttons.append(b)
        return b

    def say(self, text, color=DIM):
        self.msg.configure(text=text, fg=color)

    def busy(self, on):
        for b in self.buttons:
            b.configure(state="disabled" if on else "normal")

    def on_result(self, op, ok, err):
        pass


class DiscordDialog(_Dialog):
    """Entrar com o Discord: abre o navegador e espera o servidor confirmar."""

    def __init__(self, app):
        super().__init__(app, tr("dlg.login_title"))
        tk.Label(self.body, text=tr("dc.title"), bg=PANEL, fg=TEXT, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(self.body, text=tr("dc.intro"), bg=PANEL, fg=DIM,
                 font=("Segoe UI", 8), wraplength=330, justify="left").pack(anchor="w", pady=(2, 10))
        self.msg.pack(fill="x", pady=(4, 0))
        self.go = self.button(self.body, tr("dc.continue"), self.submit, "Accent.TButton")
        self.go.pack(fill="x", pady=(12, 0))
        self.preferences()
        self.copy = PillButton(self.body, text=tr("dc.copy"), style="Small.TButton", command=self.copy_link)
        self.bind("<Return>", lambda _e: self.submit())
        self.present()

    def submit(self):
        self.app.backend.acct_login_discord()
        self.busy(True)
        self.say(tr("dc.finish"))
        self.copy.pack(fill="x", pady=(8, 0))
        self.present()

    def copy_link(self):
        self.app._clip(self.app.backend.login_url)
        self.say(tr("dc.copied"), GREEN)

    def close(self):
        self.app.backend.acct_cancel_login()
        super().close()

    def on_result(self, op, ok, err):
        if op != "login":
            return
        self.busy(False)
        if ok:
            self.app._log(tr("log.signed_in", nick=self.app.backend.account["nick"]), "success")
            self.close()
        else:
            self.copy.pack_forget()
            self.say(str(err), RED)
            self.present()


class ProfileDialog(_Dialog):
    """Mostra a conta do Discord (nick e avatar vem de la) e deixa sair."""

    def __init__(self, app):
        super().__init__(app, tr("pf.title"), width=400)
        acc = app.backend.account
        top = tk.Frame(self.body, bg=PANEL)
        top.pack(fill="x")
        self.av = AvatarView(top, 52, bg=PANEL)
        self.av.pack(side="left")
        info = tk.Frame(top, bg=PANEL)
        info.pack(side="left", padx=(14, 0))
        tk.Label(info, text=acc["nick"], bg=PANEL, fg=TEXT, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        if acc.get("username"):
            tk.Label(info, text=f"@{acc['username']}  ·  Discord", bg=PANEL, fg=ACCENT,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
        since = time.strftime("%Y-%m-%d", time.localtime(acc.get("created", 0)))
        tk.Label(info, text=tr("pf.since", date=since), bg=PANEL, fg=DIM, font=("Segoe UI", 8)).pack(anchor="w")
        self.av.set(app.backend.avatar_png, acc["nick"][:1])

        in_game = account_game_nick(acc) or tr("pf.default_name")
        tk.Label(self.body, text=tr("pf.in_game", name=in_game), bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(14, 0))
        tk.Label(self.body, text=tr("pf.note"), bg=PANEL, fg=DIM, font=("Segoe UI", 8), wraplength=350,
                 justify="left").pack(anchor="w", pady=(4, 0))
        self.msg.pack(fill="x", pady=(10, 0))
        self.preferences()
        self.stores = {}
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.button(row, tr("store.title"), lambda: self.open_store("backgrounds")).pack(side="left", fill="x", expand=True)
        self.button(row, tr("store.characters"), lambda: self.open_store("characters")).pack(
            side="left", fill="x", expand=True, padx=(6, 0))
        self.button(self.body, tr("pf.signout"), self.logout, "Danger.TButton").pack(fill="x", pady=(10, 0))
        self.present()

    def logout(self):
        self.busy(True)
        self.app.backend.acct_logout()

    def open_store(self, category):
        store = self.stores.get(category)
        if store is not None and store.winfo_exists():
            store.lift()
            return
        self.stores[category] = ProfileStore(self, category)

    def on_result(self, op, ok, err):
        if not self.app.backend.account:                 # saiu ou a sessao expirou
            self.close()


class FightHistory(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=PANEL, padx=16, pady=14)
        self.app = app
        self.session = app.backend.session
        self.portraits = {}
        self.page = 1
        self.pages = 1

        heading = tk.Frame(self, bg=PANEL)
        heading.pack(fill="x", pady=(0, 8))
        tk.Label(heading, text=tr("history.title"), bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        self.refresh = PillButton(heading, text=tr("store.refresh"), command=lambda: self.load(1))
        self.refresh.pack(side="right")

        listing = tk.Frame(self, bg=PANEL)
        listing.pack(fill="both", expand=True)
        canvas = self.canvas = tk.Canvas(listing, bg=PANEL, highlightthickness=0)
        scroll = ttk.Scrollbar(listing, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.cards = tk.Frame(canvas, bg=PANEL)
        window = canvas.create_window(0, 0, window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        for column in range(2):
            self.cards.columnconfigure(column, weight=1, uniform="fights")
        self.bind("<MouseWheel>", self.scroll_cards)
        self.bind("<Button-4>", self.scroll_cards)
        self.bind("<Button-5>", self.scroll_cards)

        actions = tk.Frame(self, bg=PANEL)
        actions.pack(fill="x", pady=(8, 0))
        self.previous = PillButton(actions, text=tr("history.previous"), command=lambda: self.load(self.page - 1))
        self.previous.pack(side="left")
        self.next = PillButton(actions, text=tr("history.next"), command=lambda: self.load(self.page + 1))
        self.next.pack(side="right")
        self.status = tk.Label(actions, bg=PANEL, fg=TEXT)
        self.status.pack(expand=True)
        self.load(1)

    def scroll_cards(self, event):
        direction = -1 if event.num == 4 or event.delta > 0 else 1
        self.canvas.yview_scroll(direction, "units")

    def load(self, page):
        self.previous.configure(state="disabled")
        self.next.configure(state="disabled")
        self.refresh.configure(state="disabled")
        self.status.configure(text=tr("history.loading"))

        def work():
            data = api_call(DEFAULT_URL, "GET", f"/api/netplay/history/?page={page}", follow_redirects=False,
                            extra_headers={"X-Netplay-Session": self.session, "Accept-Language": get_lang()})
            paths = {player.get("portrait") for fight in data["fights"] for player in fight["players"]}
            missing = [path for path in paths if path and path not in self.portraits]
            if missing:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    for path, image in zip(missing, pool.map(self.fetch_portrait, missing)):
                        if image is not None:
                            self.portraits[path] = image
            return data

        def finished(data, error):
            self.refresh.configure(state="normal")
            if error is not None:
                self.status.configure(text=tr("history.error"))
                self.previous.configure(state="normal" if self.page > 1 else "disabled")
                self.next.configure(state="normal" if self.page < self.pages else "disabled")
                return
            self.page, self.pages = data["page"], data["pages"]
            for card in self.cards.winfo_children():
                card.destroy()
            for index, fight in enumerate(data["fights"]):
                self.add_card(index, fight)
            self.canvas.yview_moveto(0)
            self.previous.configure(state="normal" if self.page > 1 else "disabled")
            self.next.configure(state="normal" if self.page < data["pages"] else "disabled")
            self.status.configure(text=tr("history.page", page=self.page, pages=data["pages"])
                                  if data["fights"] else tr("history.empty"))

        self.app._window_task(self, work, finished)

    @staticmethod
    def fetch_portrait(path):
        if not re.fullmatch(r"/static/characters/[0-9]+(?:\.[a-f0-9]+)?\.png", path):
            return None
        try:
            from PIL import Image
            opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl_context()))
            with opener.open(DEFAULT_URL + path, timeout=4) as response:
                data = response.read(512 * 1024 + 1)
            if len(data) <= 512 * 1024:
                with Image.open(io.BytesIO(data)) as source:
                    if source.format == "PNG" and max(source.size) <= 1024:
                        image = source.convert("RGBA")
                        image.thumbnail((64, 64), Image.Resampling.LANCZOS)
                        return image
        except (OSError, ValueError, ImportError):
            return None

    def add_card(self, index, fight):
        card = tk.Frame(self.cards, bg=BG, padx=12, pady=10, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=4, pady=4)

        def line(text, color=TEXT, bold=False):
            font = ("Segoe UI", 10, "bold" if bold else "normal")
            tk.Label(card, text=text, bg=BG, fg=color, font=font, wraplength=224,
                     justify="left", anchor="w").pack(fill="x")

        date = datetime.fromisoformat(fight["date"]).astimezone().strftime("%d/%m/%Y %H:%M")
        line(f"{fight['outcome']} · {date}", ACCENT, bold=True)
        line(fight["event"] or tr("history.casual"), DIM)
        line(tr("history.rival", name=fight["rival"]), bold=True)
        matchup = tk.Frame(card, bg=BG)
        matchup.pack(fill="x", pady=8)
        matchup.columnconfigure((0, 2), weight=1, uniform="players")
        tk.Label(matchup, text="VS", bg=BG, fg=DIM).grid(row=0, column=1, padx=6)
        for slot, player in enumerate(fight["players"]):
            panel = tk.Frame(matchup, bg=PANEL, padx=6, pady=6, highlightbackground=BORDER, highlightthickness=1)
            panel.grid(row=0, column=slot * 2, sticky="nsew")
            tk.Label(panel, text=f"P{slot + 1}", bg=PANEL, fg=DIM).pack()
            tk.Label(panel, text=player["name"] or "—", bg=PANEL, fg=TEXT, wraplength=130).pack()
            image = self.portraits.get(player.get("portrait"))
            if image is not None:
                from PIL import ImageTk
                portrait = tk.Label(panel, bg=PANEL)
                portrait.image = ImageTk.PhotoImage(image, master=portrait)
                portrait.configure(image=portrait.image)
                portrait.pack()
            if player["character"]:
                tk.Label(panel, text=player["character"], bg=PANEL, fg=DIM, wraplength=130).pack()
        if fight["score"] is not None:
            line(tr("history.score", **fight["score"]), DIM)


class ProfileStore(tk.Toplevel):
    def __init__(self, profile, category):
        super().__init__(profile, bg=PANEL, padx=16, pady=14)
        self.app = profile.app
        self.session = self.app.backend.session
        self.category = category
        self.characters = category == "characters"
        self.title(tr("store.characters" if self.characters else "store.title"))
        self.minsize(620, 360)
        self.geometry("650x520")
        self.transient(profile)
        self.items, self.balance = [], 0
        self.cards = {}
        self.pending_previews = {}
        self.previews_in_flight = 0
        self.preview_job = None
        self.balance_label = tk.Label(self, bg=PANEL, fg=TEXT, anchor="w")
        self.balance_label.pack(fill="x")
        self.collection_filter = tk.StringVar(self, value="all")
        Segmented(self, [(key, tr(f"store.filter_{key}")) for key in ("all", "owned", "shop")],
                  self.collection_filter, command=self.filter_items).pack(anchor="w", pady=(8, 0))
        search_row = tk.Frame(self, bg=PANEL)
        search_row.pack(fill="x", pady=(8, 0))
        tk.Label(search_row, text=tr("store.search"), bg=PANEL, fg=TEXT).pack(side="left", padx=(0, 8))
        self.search = tk.StringVar(self)
        ttk.Entry(search_row, textvariable=self.search).pack(side="left", fill="x", expand=True)
        listing = tk.Frame(self, bg=PANEL)
        listing.pack(fill="both", expand=True, pady=8)
        scroll = ttk.Scrollbar(listing, orient="vertical")
        def view_changed(first, last):
            scroll.set(first, last)
            self.schedule_previews()

        self.canvas = tk.Canvas(listing, bg=PANEL, bd=0, highlightthickness=0, yscrollcommand=view_changed)
        scroll.configure(command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=PANEL)
        self.no_matches = tk.Label(self.grid_frame, text=tr("store.no_matches"), bg=PANEL, fg=DIM)
        for column in range(2):
            self.grid_frame.columnconfigure(column, weight=1, uniform="cards")
        grid_window = self.canvas.create_window(0, 0, window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(grid_window, width=event.width))
        self.bind("<MouseWheel>", self.scroll_cards)
        self.bind("<Button-4>", self.scroll_cards)
        self.bind("<Button-5>", self.scroll_cards)
        self.search.trace_add("write", lambda *_: self.filter_items())

        self.status = tk.Label(self, bg=PANEL, fg=DIM, anchor="w", justify="left", wraplength=550)
        self.status.pack(fill="x")
        actions = tk.Frame(self, bg=PANEL)
        actions.pack(fill="x", pady=(8, 0))
        self.refresh = PillButton(actions, text=tr("store.refresh"), command=self.load)
        self.refresh.pack(side="left")
        PillButton(actions, text=tr("store.default_character" if self.characters else "store.default"),
                   command=self.use_default).pack(side="left", padx=6)
        self.load()

    def destroy(self):
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
            self.preview_job = None
        super().destroy()

    def scroll_cards(self, event):
        direction = -1 if event.num == 4 or event.delta > 0 else 1
        self.canvas.yview_scroll(direction, "units")

    def use_default(self):
        if self.characters:
            self.app.select_character()
        else:
            self.app.select_background("")
        self.update_labels()

    def request(self, method, suffix="", body=None):
        return api_call(DEFAULT_URL, method, f"/api/netplay/store/{self.category}/" + suffix, body,
                        extra_headers={"X-Netplay-Session": self.session}, follow_redirects=False)

    def working(self, on):
        self.refresh.configure(state="disabled" if on else "normal")
        for _label, button in self.cards.values():
            button.configure(state="disabled" if on else "normal")

    def update_labels(self):
        self.balance_label.configure(text=tr("store.balance", points=self.balance))
        selected = self.app.v["character_id" if self.characters else "background_id"].get()
        for item in self.items:
            label, button = self.cards[item["id"]]
            locked = item["price"] and not item["owned"]
            if locked:
                text = "🔒 " + tr("store.price", points=item["price"])
            else:
                text = tr("store.owned" if item["owned"] else "store.free")
            if str(item["id"]) == selected:
                text += "  ✓"
            label.configure(text=text)
            if self.characters:
                button.configure(text=tr("store.buy_character" if locked else "store.apply_character"))
            else:
                button.configure(text=tr("store.buy" if locked else "store.apply"))

    def render_items(self):
        self.pending_previews.clear()
        for label, _button in self.cards.values():
            label.master.destroy()
        self.cards.clear()
        for item in self.items:
            card = tk.Frame(self.grid_frame, bg=BG, padx=10, pady=10, highlightbackground=BORDER,
                            highlightthickness=1)
            image_box = tk.Frame(card, width=240, height=135, bg=BG)
            image_box.pack(fill="x")
            image_box.pack_propagate(False)
            preview = tk.Label(image_box, text=tr("store.preview_loading"), bg=BG, fg=DIM)
            preview.pack(fill="both", expand=True)
            self.pending_previews[item["id"]] = item, preview
            tk.Label(card, text=item["name"], bg=BG, fg=TEXT, anchor="w",
                     justify="left", wraplength=240, font=("Segoe UI", 10, "bold")).pack(fill="x", pady=(6, 0))
            label = tk.Label(card, bg=BG, fg=DIM, anchor="w")
            label.pack(fill="x")
            button = PillButton(card, style="Small.TButton", command=lambda item=item: self.select(item))
            button.pack(anchor="w", pady=(6, 0))
            self.cards[item["id"]] = label, button
        self.update_labels()
        self.filter_items()

    def schedule_previews(self):
        if self.preview_job is None:
            self.preview_job = self.after_idle(self.load_visible_previews)

    def load_visible_previews(self):
        self.preview_job = None
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        for item_id, (item, preview) in list(self.pending_previews.items()):
            if self.previews_in_flight >= 4:
                break
            card = self.cards[item_id][0].master
            if not card.winfo_ismapped():
                continue
            y = card.winfo_y()
            if y >= bottom or y + card.winfo_height() <= top:
                continue
            del self.pending_previews[item_id]
            self.previews_in_flight += 1
            self.load_preview(item, preview)

    def load_preview(self, item, preview):
        def work():
            return self.app.store_thumbnail(item, self.session, self.category)

        def finished(image, error):
            self.previews_in_flight -= 1
            if preview.winfo_exists():
                if error is not None:
                    preview.configure(text=tr("store.preview_unavailable"))
                else:
                    from PIL import ImageTk
                    preview.image = ImageTk.PhotoImage(image, master=self)
                    preview.configure(text="", image=preview.image)
            self.schedule_previews()

        self.app._window_task(self, work, finished)

    @staticmethod
    def search_text(value):
        letters = unicodedata.normalize("NFKD", value.casefold())
        return "".join(letter for letter in letters if not unicodedata.combining(letter))

    def filter_items(self):
        query = self.search_text(self.search.get().strip())
        category = self.collection_filter.get()
        visible = 0
        for item in sorted(self.items, key=lambda item: not item["owned"]):
            label, _button = self.cards[item["id"]]
            card = label.master
            matches_category = category == "all" or item["owned"] == (category == "owned")
            if matches_category and query in self.search_text(item["name"]):
                card.grid(row=visible // 2, column=visible % 2, sticky="nsew", padx=(0, 8), pady=(0, 8))
                visible += 1
            else:
                card.grid_remove()
        if not visible and self.items:
            self.no_matches.grid(row=0, column=0, columnspan=2, pady=16)
        else:
            self.no_matches.grid_remove()
        self.canvas.yview_moveto(0)
        self.schedule_previews()

    def load(self):
        self.working(True)
        self.status.configure(text=tr("store.loading"))

        def finished(data, error):
            if error is None:
                self.items, self.balance = data["items"], data["balance"]
                self.render_items()
            empty = tr("store.empty_characters" if self.characters else "store.empty")
            self.status.configure(text=error if error is not None else "" if self.items else empty)
            self.working(False)

        self.app._window_task(self, lambda: self.request("GET"), finished)

    def select(self, item):
        locked = bool(item["price"] and not item["owned"])
        if locked:
            if item["price"] > self.balance:
                return messagebox.showinfo(self.title(), tr("store.insufficient"), parent=self)
            if not messagebox.askyesno(self.title(), tr("store.confirm", name=item["name"],
                                                            points=item["price"]), parent=self):
                return
        self.working(True)
        self.status.configure(text=tr("store.preparing_character" if self.characters else "store.preparing"))

        def work():
            balance = None
            if not item["owned"]:
                try:
                    balance = self.request("POST", f"{item['id']}/purchase/", {"price": item["price"]})["balance"]
                except AccountError as error:
                    if str(error) == "insufficient_balance":
                        return None, tr("store.insufficient")
                    if str(error) == "price_changed":
                        return None, tr("store.price_changed")
                    raise
            try:
                download = self.app.download_character if self.characters else self.app.download_background
                download(item, self.session)
            except Exception as error:
                return balance, str(error)
            return balance, None

        def finished(result, error):
            balance, error = result if error is None else (None, error)
            if balance is not None:
                self.balance = balance
                item["owned"] = True
                self.filter_items()
            if error is None and self.app.backend.session == self.session:
                if self.characters:
                    self.app.select_character(item)
                else:
                    self.app.select_background(item["id"])
                self.status.configure(text=tr("store.applied_character" if self.characters else "store.applied"))
            else:
                self.status.configure(text=error or tr("store.session_changed"))
            self.update_labels()
            self.working(False)

        self.app._window_task(self, work, finished)
