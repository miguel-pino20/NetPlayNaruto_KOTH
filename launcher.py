#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UN5 Netplay Launcher - FRONTEND (janela). Toda a logica esta em launcher_core.py.

Coloque os arquivos (launcher.py, launcher_core.py, launcher_theme.py, launcher_account.py, discord_auth.py,
appdata.py, i18n.py) na pasta do netplay.py e rode:
    python launcher.py

Os dados do usuario (preferencias, sessao do Discord, estado da partida) ficam em %APPDATA%\\UN5 Netplay.

Idiomas: todo texto da janela vem de i18n.tr(). O idioma fica salvo na configuracao (chave "lang"); na primeira
execucao vem de i18n.detect(). Trocar o idioma reconstroi a janela na hora (o historico do console e preservado).
"""
from __future__ import annotations

import io
import json
import math
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from release_info import VERSION

try:
    from PIL import Image, ImageDraw, ImageOps, ImageTk
except ImportError:                                       # sem Pillow: a lista de salas fica sem avatares
    Image = None

import i18n
import launcher_core as core
from rooms import RoomListener, uses_interface
from discord_auth import UA, NoRedirect, api_call, ssl_context
from i18n import has, tr
from koth_client import DEFAULT_URL, KOTH_STATES, event_for_ticket, game_downloads
from launcher_account import DiscordDialog, FightHistory, ProfileDialog
from launcher_core import SERVER_ADDR
from launcher_koth import KothPanel
from launcher_tournaments import TournamentPanel
from launcher_theme import (ACCENT, BG, BLUE, BORDER, COLORS, DIM, GREEN, MUTED, ON_ACCENT, PANEL, RED, TEXT, WARN,
                            AvatarView, PillButton, RoundFrame, Segmented, Switch, apply_style)

ROW_AV = 30                                               # lado do avatar (px) na lista de salas
GUEST_PAD = " " * 11                                      # recuo do nome do guest (espaco do avatar)

MAX_BIOS_SIZE = 8 * 1024 * 1024


def save_bios(url, destination):
    request = Request(url, headers={"User-Agent": UA})
    with urlopen(request, timeout=15, context=ssl_context()) as response:
        data = response.read(MAX_BIOS_SIZE + 1)
        if not data or len(data) > MAX_BIOS_SIZE or response.headers.get_content_type() in (
                "text/html", "application/xhtml+xml", "application/json"):
            raise ValueError(tr("games.bios_invalid"))

    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.close()
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def make_avatar(png):
    """PNG (bytes) -> PhotoImage redondo de ROW_AV px, ou None."""
    if Image is None or not png:
        return None
    try:
        big = ROW_AV * 2
        resample = getattr(Image, "Resampling", Image).LANCZOS
        im = Image.open(io.BytesIO(png)).convert("RGBA").resize((big, big), resample)
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
        im.putalpha(mask)
        return ImageTk.PhotoImage(im.resize((ROW_AV, ROW_AV), resample))
    except Exception:                                     # noqa: BLE001 - arquivo invalido: fica sem avatar
        return None


# ======================================================================================================================
# Janela principal
# ======================================================================================================================
class Launcher(tk.Tk):
    def __init__(self):
        super().__init__(className="UN5Netplay")
        self.title(f"UN5 Netplay · {VERSION}")
        icon = Path(__file__).with_name("un5-netplay.png")
        if not icon.is_file():
            icon = Path(__file__).parent / "appimage" / "un5-netplay.png"
        if icon.is_file():
            self._app_icon = tk.PhotoImage(file=str(icon))
            self.iconphoto(True, self._app_icon)
        windows_icon = Path(__file__).with_name("un5-netplay.ico")
        if os.name == "nt" and windows_icon.is_file():
            self.iconbitmap(default=str(windows_icon))
        width = min(1120, self.winfo_screenwidth() - 24)
        height = min(740, self.winfo_screenheight() - 92)
        self.geometry(f"{width}x{height}")
        self.minsize(min(980, width), min(540, height))
        self.configure(bg=BG)
        cfg = core.load_config()
        cfg["hill_url"] = DEFAULT_URL
        cfg["ignore_desync"] = False                      # debug: sempre OFF ao abrir
        cfg["lang"] = cfg.get("lang") if cfg.get("lang") in i18n.LANGS else i18n.AUTO_LANG
        i18n.set_lang(i18n.detect() if cfg["lang"] == i18n.AUTO_LANG else cfg["lang"])
        self.v = {k: (tk.BooleanVar(value=val) if isinstance(val, bool) else tk.StringVar(value=val))
                  for k, val in cfg.items()}

        mode = self.v['mode'].get()
        self.section = tk.StringVar(value=mode if mode in ('koth', 'tournaments') else 'casual')
        self.casual_transport = tk.StringVar(value='netplay')
        self.koth_category = tk.StringVar(value='casual')
        self.zerotier_rooms = None
        self.play_view_open = False
        self.background_revision = 0
        self._background_download_lock = threading.Lock()
        self.backend = core.Backend()                     # carrega a sessao do Discord salva no AppData
        self.dialog = None
        self.console_window = None
        self.games_window = None
        self.game = "un5"                                 # jogo detectado pelo CRC (ver _pick_game)
        self._after_sync = None                           # o que fazer quando o download do save padrao terminar
        self._after_allow = None
        self._koth_pending = False
        self.koth_live_event = None
        self.koth_live_ticket = ''
        self.koth_observing = False
        self.koth_live_state = {}
        self.rooms_data: dict = {}
        self.guest_imgs: dict = {}                        # id da sala -> avatar do guest (ou None)
        self.guest_labels: dict = {}                      # id da sala -> Label por cima da celula GUEST
        self._avimgs: dict = {}                           # url do avatar -> PhotoImage (precisa manter referencia)
        self._history: list = []                          # (texto, tag) do console: reaplicado ao trocar de idioma
        self.status_key, self.status_color = "READY", MUTED

        apply_style(self)
        ttk.Style(self).configure("Treeview", rowheight=ROW_AV + 8)
        self.blank_av = tk.PhotoImage(width=ROW_AV, height=ROW_AV)   # transparente: alinha linhas sem avatar
        self._build()
        self._sync_mode()
        self._refresh_account()
        self.backend.acct_restore()
        self.after(80, self._drain)
        self.after(600, self._rooms_tick)
        self._set_status("READY", MUTED)
        self._log(tr("log.server", addr=SERVER_ADDR), "dim")
        self._log(tr("log.data", path=core.DATA_DIR), "dim")
        self._log(tr("log.hint"), "dim")

    # ================================================================ configuracao completa
    def raw(self) -> dict:
        return {k: v.get() for k, v in self.v.items()}

    def cfg(self) -> dict:
        """Escolhas da tela + tudo que e fixo/detectado (core.full_config) + o nick do perfil do Discord."""
        cfg = core.full_config(self.raw(), self.backend.is_admin(), getattr(self, "game", "un5"))
        acc = self.backend.account
        cfg["nick"] = core.account_game_nick(acc) if acc else ""
        return cfg

    # ================================================================ idioma
    def _change_lang(self):
        preference = self.v["lang"].get()
        code = i18n.detect() if preference == i18n.AUTO_LANG else preference
        if code not in i18n.LANGS:
            return
        core.save_config({**self.raw(), "ignore_desync": False})
        if code == i18n.get_lang():
            return
        i18n.set_lang(code)

        def rebuild_account():
            reopen = self.dialog is not None
            self._rebuild()
            if reopen:
                self.open_account()

        self.after_idle(rebuild_account)

    def _change_background(self):
        core.save_config({**self.raw(), "ignore_desync": False})
        self._redraw_background()
        self._sync_rooms_preview()

    def _fetch_store_image(self, item_id, session, action, maximum, category="backgrounds", *, version=None):
        url = f"{DEFAULT_URL}/api/netplay/store/{category}/{item_id}/{action}/"
        headers = {"User-Agent": UA, "X-Netplay-Session": session}
        if version:
            headers["If-Match"] = f'"{version}"'
        request = Request(url, headers=headers)
        opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl_context()))
        try:
            with opener.open(request, timeout=15) as response:
                data = response.read(maximum + 1)
        except HTTPError as error:
            if error.code == 412:
                raise ValueError(tr("store.image_changed")) from None
            raise
        if len(data) > maximum:
            raise ValueError(tr("store.invalid_image"))
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP") or max(source.size) > 4096:
                raise ValueError(tr("store.invalid_image"))
            return ImageOps.exif_transpose(source).convert("RGBA")

    def store_thumbnail(self, item, session, category):
        item_id = int(item["id"])
        version = item.get("image_version") or ""
        cache = None
        if re.fullmatch(r"[0-9a-f]{64}", version):
            cache = core.DATA_DIR / "store_previews" / category / f"{item_id}-{version}.png"
            try:
                with Image.open(cache) as source:
                    return source.convert("RGBA")
            except OSError:
                pass

        source_path = None
        if not item["price"] or item["owned"]:
            if category == "characters":
                candidate = self._character_folder(item_id, version) / "idle.png"
                if candidate.is_file():
                    source_path = candidate
            else:
                source_path = self._cached_background(item)
        if source_path is not None:
            with Image.open(source_path) as source:
                image = source.convert("RGBA")
        else:
            image = self._fetch_store_image(item_id, session, "preview", 1024 * 1024, category)
        image.thumbnail((240, 135), Image.Resampling.LANCZOS)
        if cache is not None:
            try:
                self._save_store_png(image, cache)
            except OSError:
                pass
        return image

    @staticmethod
    def _cached_background(item):
        path = core.DATA_DIR / "backgrounds" / f"{int(item['id'])}.png"
        if not path.is_file():
            return None
        version = item.get("image_version")
        if version:
            try:
                saved = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if saved != {"version": version}:
                return None
        return path

    def download_background(self, item, session):
        item_id = int(item["id"])
        with self._background_download_lock:
            cached = self._cached_background(item)
            if cached is not None:
                return cached
            image = self._fetch_store_image(item_id, session, "download", 12 * 1024 * 1024)
            path = core.DATA_DIR / "backgrounds" / f"{item_id}.png"
            self._save_store_png(image, path)
            core.write_json(path.with_suffix(".json"), {"version": item.get("image_version")}, private=True)
            return path

    @staticmethod
    def _save_store_png(image, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                image.save(output, format="PNG")
                output.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    def select_background(self, item_id):
        self.background_revision += 1
        self.v["background_id"].set(str(item_id))
        self.v["show_background"].set(True)
        self._change_background()

    @staticmethod
    def _character_folder(item_id, version):
        if not re.fullmatch(r"[0-9]+", str(item_id)) or not re.fullmatch(r"[0-9a-f]{64}", version):
            raise ValueError(tr("store.invalid_image"))
        return core.DATA_DIR / "characters" / f"{item_id}-{version}"

    def download_character(self, item, session):
        folder = self._character_folder(item["id"], item["image_version"])
        assets = {"download": folder / "idle.png"}
        if item.get("has_poses"):
            assets["poses"] = folder / "poses.png"
        with self._background_download_lock:
            for action, path in assets.items():
                if path.is_file():
                    continue
                image = self._fetch_store_image(item["id"], session, action, 12 * 1024 * 1024, "characters",
                                                version=item["image_version"])
                if not image.getbbox():
                    raise ValueError(tr("store.invalid_image"))
                self._save_store_png(image, path)

    def select_character(self, item=None):
        self.v["character_id"].set(str(item["id"]) if item else "")
        self.v["character_version"].set(item["image_version"] if item else "")
        for canvas in (self.home_mascot, self.sidebar_mascot):
            if canvas is not None:
                canvas.reload_character()
        core.save_config({**self.raw(), "ignore_desync": False})

    def _rebuild(self):
        """Reconstroi a janela inteira no idioma atual. O console e o status sao restaurados."""
        reopen_games = self.games_window is not None and self.games_window.winfo_exists()
        reopen_console = self.console_window is not None
        if reopen_console:
            self._close_console()
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.destroy()
        self.dialog = None
        for w in self.winfo_children():
            w.destroy()
        self.guest_imgs, self.guest_labels = {}, {}
        self._build()
        self._sync_mode()
        self._refresh_account()
        self._set_buttons(self.backend.running or self._koth_pending)
        self._log(tr("log.lang"), "info")
        if reopen_console:
            self.open_console()
        if reopen_games:
            self.open_games()
        self._relayout()
        self.after(80, self._relayout)
        self.after(300, self._relayout)

    # ================================================================ layout
    def _relayout(self):
        """Depois de reconstruir a janela (troca de idioma): recalcula, de dentro para fora, todos os cards
        arredondados com o tamanho real, sem depender dos eventos <Configure> (que podem nao chegar)."""
        frames = []

        def walk(w):
            for c in w.winfo_children():
                walk(c)
                if isinstance(c, RoundFrame):
                    frames.append(c)
        try:
            for _ in range(3):
                frames.clear()
                walk(self)
                self.update_idletasks()
                for rf in frames:
                    rf.refresh()
            self.update_idletasks()
        except tk.TclError:
            pass

    def _build(self):
        head = self._header()

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.history_view = None
        self._navigation(body)

        # Keep the existing session widgets available to callbacks while redesigning the main view.
        session_view = self.session_view = tk.Frame(body, bg=BG)
        if self.play_view_open:
            session_view.pack(fill="both", expand=True)
        left = tk.Frame(session_view, bg=BG, width=360)
        left.pack(side="left", fill="y", padx=(22, 18), pady=(12, 0))
        left.pack_propagate(False)
        self._card_main(left)
        sidebar_mascot = self.sidebar_mascot = self._build_mascot(left)
        if sidebar_mascot is not None:
            sidebar_mascot.pack(fill="both", expand=True)
        self.home_mascot = self._build_mascot(body)
        self._show_home_mascot()

        right = tk.Frame(session_view, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 22), pady=(12, 0))
        self._rooms_panel(right)                          # as salas ocupam o resto: e a informacao principal
        self.koth_panel = KothPanel(right, self, self.koth_box)
        self.tournaments = TournamentPanel(right, self, self.play_actions, self.tournament_box)
        self._build_background(head, body, session_view, left, right, sidebar_mascot=sidebar_mascot)

        foot = tk.Frame(self, bg=BG, padx=22, pady=8)
        foot.pack(fill="x")
        tk.Label(foot, text=tr("footer"), bg=BG, fg=DIM, font=("Segoe UI", 8)).pack(side="left")

    def _build_mascot(self, parent):
        if Image is None:
            return
        default_idle = Path(__file__).with_name("assets") / "naruto_mascot.png"
        default_poses = default_idle.with_name("naruto_mascot_poses.png")
        poses = {}
        canvas = tk.Canvas(parent, bg=BG, width=1, height=1, bd=0, highlightthickness=0)
        canvas.create_image(0, 0, anchor="nw", tags="backdrop")
        clone = canvas.create_image(0, 0, anchor="s", state="hidden")
        mascot = canvas.create_image(0, 0, anchor="s")
        current_size = None
        images = {}

        def resize(width, height):
            nonlocal current_size
            size = (min(200, width - 20), min(270, height - 20))
            if min(size) < 48 or not poses:
                canvas.itemconfigure(mascot, state="hidden")
                return
            if size != current_size:
                for name, pose in poses.items():
                    frame = pose.copy()
                    limit = tuple(int(edge * 0.78) for edge in size) if name == "charge" and canvas.builtin_character else size
                    frame.thumbnail(limit, Image.Resampling.LANCZOS)
                    images[name] = ImageTk.PhotoImage(frame, master=canvas)
                    if name == "charge" and canvas.builtin_character:
                        images["assist"] = ImageTk.PhotoImage(ImageOps.mirror(frame), master=canvas)
                canvas.mascot_image = images["idle"]
                canvas.itemconfigure(mascot, image=images["idle"])
                canvas.itemconfigure(clone, image=images["idle"])
                current_size = size
            canvas.coords(mascot, width // 2, (height + images["idle"].height()) // 2)
            canvas.itemconfigure(mascot, state="normal")

        restart = self._animate_mascot(canvas, mascot, clone, images)

        def crop_pose(image, builtin):
            if builtin:
                bounds = image.getbbox()
            else:
                # Ignore faint pixels in transparent margins when sizing downloaded poses.
                alpha = image.getchannel("A").point(lambda value: 255 if value >= 32 else 0)
                bounds = alpha.getbbox()
                if bounds:
                    x0, y0, x1, y1 = bounds
                    bounds = (max(0, x0 - 2), max(0, y0 - 2),
                              min(image.width, x1 + 2), min(image.height, y1 + 2))
            return image.crop(bounds) if bounds else None

        def reload_character():
            nonlocal current_size
            item_id = self.v["character_id"].get()
            version = self.v["character_version"].get()
            paths = [(default_idle, default_poses, True)]
            if item_id:
                try:
                    folder = self._character_folder(item_id, version)
                    paths.insert(0, (folder / "idle.png", folder / "poses.png", False))
                except ValueError:
                    pass
            poses.clear()
            for idle_path, sheet_path, builtin in paths:
                try:
                    with Image.open(idle_path) as source:
                        idle = crop_pose(source.convert("RGBA"), builtin)
                except OSError:
                    continue
                if idle is None:
                    continue
                poses["idle"] = idle
                canvas.builtin_character = builtin
                try:
                    with Image.open(sheet_path) as source:
                        sheet = source.convert("RGBA")
                        width, height = sheet.width // 2, sheet.height // 2
                        for index, name in enumerate(("charge", "release", "sign", "land")):
                            x, y = index % 2 * width, index // 2 * height
                            pose = crop_pose(sheet.crop((x, y, x + width, y + height)), builtin)
                            if pose is not None:
                                poses[name] = pose
                except OSError:
                    pass
                break
            restart()
            images.clear()
            current_size = None
            resize(canvas.winfo_width(), canvas.winfo_height())

        canvas.reload_character = reload_character
        canvas.bind("<Configure>", lambda event: resize(event.width, event.height))
        reload_character()
        return canvas

    @staticmethod
    def _animate_mascot(canvas, mascot, clone, images):
        # Pose changes are defined in seconds from the start of each attack.
        attacks = (
            ("rasengan", ((0.0, "sign"), (0.20, "charge"), (0.84, "release"), (1.26, "land"))),
            ("clone", ((0.0, "sign"), (0.60, "land"), (1.02, "idle"))),
        )
        next_attack = 0
        timer = None
        started = 0.0
        playing = False

        def clear():
            canvas.delete("mascot-effect")
            canvas.itemconfigure(clone, state="hidden")
            if images:
                canvas.itemconfigure(mascot, image=images["idle"])
                canvas.coords(mascot, canvas.winfo_width() // 2,
                              (canvas.winfo_height() + images["idle"].height()) // 2)

        def begin():
            nonlocal started, playing
            started = time.monotonic()
            playing = True
            tick()

        def tick():
            nonlocal timer, next_attack, playing
            timer = None
            if not canvas.winfo_ismapped():
                return
            elapsed = time.monotonic() - started
            if elapsed >= 1.55 or not images or canvas.itemcget(mascot, "state") == "hidden":
                playing = False
                clear()
                next_attack = (next_attack + 1) % len(attacks)
                timer = canvas.after(14000, begin)
                return
            builtin = canvas.builtin_character and {"assist", "release", "sign", "land"} <= images.keys()
            if builtin:
                effect, timeline = attacks[next_attack]
                pose = next(name for at, name in reversed(timeline) if elapsed >= at)
            else:
                effect = "gesture"
                pose = ("charge", "release", "sign", "land", "idle")[min(4, int(elapsed / 0.29))]
            frame = images.get(pose, images["idle"])
            x = canvas.winfo_width() // 2
            feet = (canvas.winfo_height() + images["idle"].height()) // 2
            canvas.delete("mascot-effect")
            canvas.itemconfigure(mascot, image=frame)
            if effect == "rasengan" and pose in ("charge", "release"):
                if pose == "charge":
                    spread = min(1, (elapsed - 0.20) / 0.20)
                    separation = frame.width() * 0.64 * spread
                    x += separation / 2
                    canvas.coords(clone, x - separation, feet)
                    canvas.itemconfigure(clone, image=images["assist"], state="normal")
                else:
                    canvas.itemconfigure(clone, state="hidden")
                    x -= int(22 * math.sin(math.pi * (elapsed - 0.84) / 0.42))
                cx = x - frame.width() * (0.31 if pose == "charge" else 0.29)
                cy = feet - frame.height() * (0.36 if pose == "charge" else 0.56)
                radius = max(4, min(frame.height() * 0.15, (elapsed - 0.20) * 55))
                bounds = (cx - radius, cy - radius, cx + radius, cy + radius)
                canvas.create_oval(*bounds, fill="#2485e8", outline="#9fefff", width=2, tags="mascot-effect")
                for offset in (0, 140):
                    canvas.create_arc(*bounds, start=(elapsed * 720 + offset) % 360, extent=95,
                                      style="arc", outline="#e9fbff", width=3, tags="mascot-effect")
            elif effect == "clone" and elapsed >= 0.48:
                progress = min(1, (elapsed - 0.48) / 0.28, (1.55 - elapsed) / 0.26)
                offset = min(canvas.winfo_width() * 0.18, images["idle"].width() * 0.74) * progress
                x -= int(offset / 2)
                canvas.coords(clone, x + offset * 1.5, feet - 5)
                canvas.itemconfigure(clone, image=images["idle"], state="normal")
            if effect == "gesture" and len(images) == 1:
                feet -= int(12 * math.sin(math.pi * min(1, elapsed / 1.16)))
            canvas.coords(mascot, x, feet)
            timer = canvas.after(33, tick)

        def show(_event):
            nonlocal timer
            if timer is None:
                timer = canvas.after(6500, begin)

        def hide(_event):
            nonlocal timer, playing
            playing = False
            if timer is not None:
                canvas.after_cancel(timer)
                timer = None
            if canvas.winfo_exists():
                clear()

        def activate(_event):
            if playing or not images:
                return
            if timer is not None:
                canvas.after_cancel(timer)
            begin()

        canvas.tag_bind(mascot, "<Button-1>", activate)
        canvas.tag_bind(mascot, "<Enter>", lambda _event: canvas.configure(cursor="hand2"))
        canvas.tag_bind(mascot, "<Leave>", lambda _event: canvas.configure(cursor=""))
        canvas.bind("<Map>", show, add="+")
        canvas.bind("<Unmap>", hide, add="+")
        canvas.bind("<Destroy>", hide, add="+")

        def restart():
            nonlocal next_attack
            hide(None)
            next_attack = 0
            if canvas.winfo_ismapped():
                show(None)

        return restart

    def _show_home_mascot(self):
        if self.home_mascot is not None:
            if self.play_view_open or self.history_view is not None:
                self.home_mascot.place_forget()
            else:
                self.home_mascot.place(x=92, rely=1, y=-32, anchor="sw", width=220, height=290)

    def _navigation(self, parent):
        bar = tk.Frame(parent, bg=PANEL, padx=22, pady=4)
        bar.pack(fill="x")
        menus = (
            ("nav.play", (("menu.pvp", lambda: self._open_play("casual")),
                          ("hill.title", lambda: self._open_play("koth")),
                          ("nav.tournaments", lambda: self._open_play("tournaments")))),
            ("menu.games", (("games.catalog", self.open_games),)),
            ("menu.help", tuple((f"help.{topic}", lambda topic=topic: self._show_guide(
                f"help.{topic}", f"help.{topic}_body"))
                for topic in ("setup", "host", "join", "create_koth", "create_tournament"))),
        )
        for title, entries in menus:
            button = tk.Menubutton(bar, text=tr(title), bg=PANEL, fg=TEXT, activebackground=ACCENT,
                                   activeforeground=ON_ACCENT, padx=12, pady=5, takefocus=True)
            button.pack(side="left")
            menu = tk.Menu(button, tearoff=False, bg=PANEL, fg=TEXT, activebackground=ACCENT,
                           activeforeground=ON_ACCENT)
            for label, command in entries:
                menu.add_command(label=tr(label), command=command)
            if title == "menu.help":
                self.help_nav = button
                menu.add_separator()
                menu.add_command(label=tr("menu.logs"), command=self.open_console)
            button.configure(menu=menu)
            button.bind("<Return>", lambda _event, b=button, m=menu: m.tk_popup(
                b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))

        self.history_nav = tk.Button(bar, text=tr("history.title"), command=self._open_history,
                                     bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=ON_ACCENT,
                                     padx=12, pady=5, relief="flat", borderwidth=0, takefocus=True)
        self.close_play_btn = PillButton(bar, text="× " + tr("nav.close_view"), style="Small.TButton",
                                        command=self._close_play)
        if self.play_view_open:
            self.close_play_btn.pack(side="right")

    def _open_history(self):
        if not self.backend.account or not self.backend.session:
            return
        if self.history_view is None:
            self.play_view_open = False
            self.session_view.pack_forget()
            self.history_view = FightHistory(self.session_view.master, self)
            self.history_view.pack(fill="both", expand=True, padx=22, pady=12)
            self.close_play_btn.pack(side="right")
            self._show_home_mascot()

    def _destroy_history(self):
        if self.history_view is not None:
            self.history_view.destroy()
            self.history_view = None

    def _open_play(self, section):
        self._destroy_history()
        self.play_view_open = True
        self._show_home_mascot()
        self.section.set(section)
        self._select_section()
        self.session_view.pack(fill="both", expand=True)
        self.close_play_btn.pack(side="right")
        if self.section.get() == "casual":
            self._rooms_refresh()

    def _close_play(self):
        self._destroy_history()
        self.play_view_open = False
        self.session_view.pack_forget()
        self.close_play_btn.pack_forget()
        self._show_home_mascot()

    def _show_guide(self, title, content):
        messagebox.showinfo(tr(title), tr(content), parent=self)

    def open_games(self):
        if self.games_window is not None and self.games_window.winfo_exists():
            self.games_window.deiconify()
            self.games_window.lift()
            return
        window = self.games_window = tk.Toplevel(self, bg=BG)
        window.title(tr("games.catalog"))
        window.minsize(600, 300)
        content = tk.Frame(window, bg=BG, padx=18, pady=16)
        content.pack(fill="both", expand=True)
        buttons = {}
        for crc, game in core.GAMES.items():
            card = RoundFrame(content, radius=14, padx=14, pady=10)
            card.pack(fill="x", pady=(0, 8))
            inner = card.inner
            self._label(inner, tr(f"menu.{game}"))
            self._note(inner, tr("games.details", crc=crc), wrap=530)
            actions = tk.Frame(inner, bg=PANEL)
            actions.pack(fill="x", pady=(8, 0))
            rom = PillButton(actions, text=tr("games.download"), style="Small.TButton", state="disabled")
            bios = PillButton(actions, text=tr("games.bios_link"), style="Small.TButton", state="disabled")
            rom.pack(side="left", padx=(0, 8))
            bios.pack(side="left")
            buttons[game] = rom, bios

        catalog_status = tk.StringVar(window, value=tr("games.loading_links"))
        tk.Label(content, textvariable=catalog_status, bg=BG, fg=DIM, anchor="w", justify="left",
                 wraplength=550).pack(fill="x", pady=(0, 8))

        def apply_links(links, error):
            if error is not None:
                catalog_status.set(tr("games.links_failed"))
                return
            pending = False
            for game, (rom, bios) in buttons.items():
                urls = links.get(game, {})
                rom_url, bios_url = urls.get("rom_url"), urls.get("bios_url")
                if rom_url:
                    rom.configure(state="normal", command=lambda url=rom_url: webbrowser.open(url))
                if bios_url:
                    bios.configure(state="normal", command=lambda g=game, url=bios_url, b=bios:
                                   self._download_bios(window, g, url, b, catalog_status))
                pending |= not (rom_url and bios_url)
            catalog_status.set(tr("games.pending_links") if pending else "")

        self._window_task(window, lambda: game_downloads(DEFAULT_URL), apply_links)

        status = tk.StringVar(window, value=tr("games.open_pcsx2"))
        validate = PillButton(content, text=tr("games.validate"), style="Small.TButton",
                              command=lambda: self._validate_catalog(window, validate, status))
        validate.pack(anchor="w", pady=(4, 0))
        tk.Label(content, textvariable=status, bg=BG, fg=TEXT, anchor="w", justify="left",
                 wraplength=550).pack(fill="x", pady=(8, 0))

    def _download_bios(self, window, game, url, button, status):
        filename = filedialog.asksaveasfilename(parent=window, title=tr("games.bios_save"),
                                               initialfile=f"{game.upper()}-BIOS.bin", defaultextension=".bin",
                                               filetypes=[("BIOS", "*.bin"), ("*", "*")])
        if not filename:
            return
        button.configure(state="disabled")
        status.set(tr("games.bios_downloading", game=game.upper()))

        def finished(_value, error):
            button.configure(state="normal")
            if error is not None:
                status.set(tr("games.bios_failed", error=error))
            else:
                status.set(tr("games.bios_saved", path=filename))

        self._window_task(window, lambda: save_bios(url, Path(filename)), finished)

    def _validate_catalog(self, window, button, status):
        if self.backend.running or self._koth_pending:
            status.set(tr("err.busy"))
            return

        status.set(tr("run.testing_pine"))
        button.configure(state="disabled")
        def finished(value, error):
            game, crc = value if error is None else (None, None)
            if error is not None:
                message = tr("dlg.game_pine", exc=error)
            elif game is None:
                message = tr("log.game_unknown", crc=crc or "?")
            else:
                message = tr("games.valid", game=tr(f"menu.{game}"), crc=crc)
            status.set(message)
            button.configure(state="normal")

        self._window_task(window, lambda: core.detect_game(core.FIXED["pine_slot"]), finished)

    def _window_task(self, window, work, done):
        result = queue.SimpleQueue()

        def run():
            try:
                result.put((work(), None))
            except Exception as exc:
                result.put((None, str(exc)))

        def poll():
            if not window.winfo_exists():
                return
            try:
                value, error = result.get_nowait()
            except queue.Empty:
                self.after(80, poll)
                return
            done(value, error)

        threading.Thread(target=run, daemon=True).start()
        self.after(80, poll)

    def _build_background(self, head, body, *columns, sidebar_mascot=None):
        self._redraw_background = lambda: None
        previews = ((self.rooms_preview, self.rooms_tree), (self.koth_panel.list_background, self.koth_panel.tree))
        if Image is None:
            return
        backdrop_canvases = [canvas for canvas in (self.brand, self.home_mascot, sidebar_mascot)
                            if canvas is not None]
        default_path = Path(__file__).with_name("assets") / "background" / "background1.png"
        artwork = None
        loaded_id = None
        layers = []
        for frame in (head, body, *columns):
            layer = tk.Label(frame, bd=0, highlightthickness=0, bg=BG)
            layer.place(x=0, y=0, relwidth=1, relheight=1, bordermode="outside")
            layer.lower()
            layers.append((frame, layer))

        pending = None

        def redraw():
            nonlocal pending, artwork, loaded_id
            pending = None
            body_top = body.winfo_y() - head.winfo_y()
            width, height = body.winfo_width(), body_top + body.winfo_height()
            if not self.v["show_background"].get():
                for _frame, layer in layers:
                    layer.configure(image="")
                    layer.background_image = None
                for canvas in backdrop_canvases:
                    canvas.itemconfigure("backdrop", image="")
                    canvas.background_image = None
                for preview, _tree in previews:
                    preview.artwork = None
                    preview.place_forget()
                return
            if min(width, height) <= 1:
                return
            selected_id = self.v["background_id"].get()
            source_key = selected_id, self.background_revision
            if source_key != loaded_id:
                loaded_id, artwork = source_key, None
                candidates = [default_path]
                if selected_id.isascii() and selected_id.isdecimal():
                    candidates.insert(0, core.DATA_DIR / "backgrounds" / f"{selected_id}.png")
                for path in candidates:
                    try:
                        with Image.open(path) as source:
                            background = Image.new("RGBA", source.size, BG)
                            background.alpha_composite(source.convert("RGBA"))
                    except OSError:
                        continue
                    if path == default_path:
                        background = background.crop((0, 28, background.width, background.height))
                    background = background.convert("RGB")
                    artwork = Image.blend(background, Image.new("RGB", background.size, BG), 0.22)
                    break
            if artwork is None:
                return
            resample = getattr(Image, "Resampling", Image).LANCZOS
            fitted = ImageOps.fit(artwork, (width, height), method=resample)
            def crop(frame):
                x = frame.winfo_rootx() - head.winfo_rootx()
                y = frame.winfo_rooty() - head.winfo_rooty()
                return fitted.crop((x, y, x + frame.winfo_width(), y + frame.winfo_height()))

            for frame, layer in layers:
                if frame.winfo_ismapped():
                    layer.background_image = ImageTk.PhotoImage(crop(frame), master=body)
                    layer.configure(image=layer.background_image)

            for canvas in backdrop_canvases:
                if canvas.winfo_ismapped():
                    canvas.background_image = ImageTk.PhotoImage(crop(canvas), master=body)
                    canvas.itemconfigure("backdrop", image=canvas.background_image)
            for preview, tree in previews:
                wrap = preview.master
                if wrap.winfo_ismapped() and min(wrap.winfo_width(), wrap.winfo_height()) > 1:
                    image = crop(wrap)
                    preview.artwork = Image.blend(image, Image.new("RGB", image.size, PANEL), 0.22)
                    preview.bounds = None
                    self._sync_tree_preview(preview, tree)

        def schedule(_event=None):
            nonlocal pending
            if pending is not None:
                body.after_cancel(pending)
            pending = body.after(40, redraw)

        def cancel(_event):
            if pending is not None:
                body.after_cancel(pending)

        for frame, _layer in layers:
            frame.bind("<Configure>", schedule, add="+")
            frame.bind("<Map>", schedule, add="+")
        for preview, _tree in previews:
            for event in ("<Configure>", "<Map>"):
                preview.master.bind(event, schedule, add="+")
        for canvas in backdrop_canvases:
            canvas.bind("<Configure>", schedule, add="+")
            canvas.bind("<Map>", schedule, add="+")
        body.bind("<Destroy>", cancel, add="+")
        self._redraw_background = schedule
        schedule()

    def _header(self):
        head = tk.Frame(self, bg=BG, padx=22, pady=14)
        head.pack(fill="x")
        title_font = tkfont.Font(font=("Segoe UI", 21, "bold"))
        subtitle_font = tkfont.Font(font=("Segoe UI", 8, "bold"))
        subtitle = tr("subtitle")
        self._brand_logo = None
        if Image is not None:
            logo_path = Path(__file__).with_name("assets") / "logo_naruto.png"
            try:
                with Image.open(logo_path) as source:
                    logo = source.convert("RGBA")
                logo = logo.crop(logo.getbbox())
                logo.thumbnail((80, 64), getattr(Image, "Resampling", Image).LANCZOS)
                self._brand_logo = ImageTk.PhotoImage(logo, master=head)
            except OSError:
                pass
        if self._brand_logo is None and hasattr(self, "_app_icon"):
            self._brand_logo = self._app_icon.subsample(8, 8)
        title_x = self._brand_logo.width() + 16 if self._brand_logo else 18
        width = title_x + max(title_font.measure("UN5 NETPLAY"), subtitle_font.measure(subtitle)) + 4
        self.brand = tk.Canvas(head, width=width, height=64, bg=BG, bd=0, highlightthickness=0)
        self.brand.pack(side="left")
        self.brand.create_image(0, 0, anchor="nw", tags="backdrop")
        if self._brand_logo:
            self.brand.create_image(0, 32, image=self._brand_logo, anchor="w")
        else:
            self.brand.create_rectangle(0, 10, 5, 54, fill=ACCENT, outline="")
        for text, y, font, color in (
            ("UN5 NETPLAY", 22, title_font, TEXT), (subtitle, 49, subtitle_font, TEXT),
        ):
            self.brand.create_text(title_x + 1, y + 1, text=text, anchor="w", font=font, fill=BG)
            self.brand.create_text(title_x, y, text=text, anchor="w", font=font, fill=color)
        self.brand.fonts = title_font, subtitle_font
        self._account_strip(head)
        return head

    # ---- faixa da conta (cabecalho)
    def _account_strip(self, parent):
        strip = RoundFrame(parent, radius=16, padx=12, pady=7, stretch=False)
        strip.pack(side="right")
        inner = strip.inner
        self.acct_av = AvatarView(inner, 30, bg=PANEL)
        self.acct_av.pack(side="left")
        box = tk.Frame(inner, bg=PANEL)
        box.pack(side="left", padx=(10, 0))
        self.acct_name = tk.Label(box, text=tr("acct.guest"), bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold"),
                                  anchor="w")
        self.acct_name.pack(anchor="w")
        self.acct_sub = tk.Label(box, text=tr("acct.login"), bg=PANEL, fg=ACCENT, font=("Segoe UI", 8, "bold"),
                                 anchor="w")
        self.acct_sub.pack(anchor="w")
        for w in (strip, inner, self.acct_av, box, self.acct_name, self.acct_sub):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda _e: self.open_account())

    def open_account(self):
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        if self.backend.account:
            self.load_store_balance()
        self.dialog = (ProfileDialog if self.backend.account else DiscordDialog)(self)

    def load_store_balance(self):
        session = self.backend.session
        if not self.backend.account or not session:
            return
        request = self._balance_request = object()

        def work():
            return api_call(DEFAULT_URL, "GET", "/api/netplay/store/backgrounds/",
                            extra_headers={"X-Netplay-Session": session}, follow_redirects=False)["balance"]

        def finished(balance, error):
            if error is None and self._balance_request is request:
                self.set_store_balance(balance, session)

        self._window_task(self.acct_sub, work, finished)

    def set_store_balance(self, points, session):
        if self.backend.account and session == self.backend.session:
            self._balance_request = None
            self.acct_sub.configure(text=f'{tr("acct.profile")}  ·  {tr("acct.store_points", points=points)}')

    def _refresh_account(self):
        acc, png = self.backend.account, self.backend.avatar_png
        if acc and self.backend.session:
            self.history_nav.pack(side="left", after=self.help_nav)
        else:
            self.history_nav.pack_forget()
        self.acct_name.configure(text=acc["nick"] if acc else tr("acct.guest"))
        self._balance_request = None
        self.acct_sub.configure(text=tr("acct.profile") if acc else tr("acct.login"))
        self.load_store_balance()
        self.acct_av.set(png if acc else None, acc["nick"][:1] if acc else "?")
        self._nick_hint()
        self._sync_admin()
        self._set_buttons(self.backend.running)           # PREPARE so existe para o dono

    def _on_acct(self, op, ok, err):
        if self.history_view is not None and (
            not self.backend.account or self.history_view.session != self.backend.session
        ):
            self._close_play()
        self._refresh_account()
        if op == "restore":
            if ok:
                self._log(tr("log.signed_in", nick=self.backend.account["nick"]), "success")
            else:
                self._log(tr("log.login_not_restored", err=err), "warn")
        elif op == "logout":
            self._log(tr("log.signed_out"), "info")
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.on_result(op, ok, err)

    def _card(self, parent, number, title):
        card = RoundFrame(parent, radius=18, padx=16, pady=14)
        card.pack(fill="x", pady=(0, 13))
        inner = card.inner
        head = tk.Frame(inner, bg=PANEL)
        head.pack(fill="x", pady=(0, 6))
        tk.Label(head, text=number, bg=ACCENT, fg=ON_ACCENT, font=("Segoe UI", 9, "bold"), width=2).pack(side="left")
        tk.Label(head, text=title, bg=PANEL, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(side="left", padx=(9, 0))
        return inner

    def _label(self, parent, text):
        tk.Label(parent, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(7, 3))

    def _note(self, parent, text, wrap=300):
        tk.Label(parent, text=text, bg=PANEL, fg=DIM, font=("Segoe UI", 8), wraplength=wrap,
                 justify="left").pack(anchor="w", pady=(5, 0))

    # ---- card unico: jogador + partida + executar (o nick vem do Discord: nao ha campo)
    def _card_main(self, parent):
        card = RoundFrame(parent, radius=18, padx=16, pady=14)
        card.pack(side="top", fill="x", anchor="n")
        inner = card.inner
        tk.Label(inner, text=tr("card.match"), bg=PANEL, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w",
                                                                                                    pady=(0, 6))

        tk.Label(inner, text=tr("playing_as"), bg=PANEL, fg=ACCENT, font=("Segoe UI", 8, "bold")).pack(anchor="w",
                                                                                                     pady=(2, 3))
        self.nick_hint = tk.Label(inner, text="", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold"), anchor="w",
                                  justify="left", wraplength=300)
        self.nick_hint.pack(anchor="w")
        self.nick_sub = tk.Label(inner, text="", bg=PANEL, fg=DIM, font=("Segoe UI", 8), anchor="w",
                                 justify="left", wraplength=300)
        self.nick_sub.pack(anchor="w", pady=(2, 0))

        self.casual_box = tk.Frame(inner, bg=PANEL)
        self.casual_box.pack(fill='x')
        Segmented(self.casual_box, [('netplay', 'Netplay'), ('zerotier', 'ZeroTier')], self.casual_transport,
                  self._change_transport).pack(fill='x', pady=(8, 0))
        game_row = tk.Frame(self.casual_box, bg=PANEL)
        game_row.pack(fill="x", pady=(8, 0))
        tk.Label(game_row, text=tr("koth.game"), bg=PANEL, fg=TEXT).pack(side="left")
        pvp_game = self.v["pvp_game"]
        self.pvp_game_picker = ttk.Combobox(game_row, textvariable=pvp_game, values=("UN5", "UN6"),
                                           state="readonly", width=8)
        self.pvp_game_picker.pack(side="right")
        if pvp_game.get() not in ("UN5", "UN6"):
            pvp_game.set(core.DEFAULTS["pvp_game"])
        self.pvp_game_picker.bind("<<ComboboxSelected>>", self._sync_pvp_state_picker)
        self._note(self.casual_box, tr("note.delay"))
        self.zt_states = tk.Frame(self.casual_box, bg=PANEL)
        tk.Label(self.zt_states, text=tr("zt.state_title"), bg=PANEL, fg=TEXT).pack(side="left")
        self.zt_state_picker = ttk.Menubutton(self.zt_states)
        self.zt_state_picker.pack(side="right")
        state_menu = tk.Menu(self.zt_state_picker, tearoff=False)
        self.zt_state_picker.configure(menu=state_menu)
        selection = self.v["zerotier_state"]
        self.zt_state_picker.configure(text=tr("zt.state_" + selection.get()) if selection.get() in
                                       ("standard", "transformed", "audio20") else tr("zt.state_standard"))
        for key in ("standard", "transformed", "audio20"):
            label = tr("zt.state_" + key)
            state_menu.add_radiobutton(label=label, value=key, variable=selection,
                                       command=lambda label=label: self.zt_state_picker.configure(text=label))

        self.mode_box = tk.Frame(inner, bg=PANEL)
        self.mode_box.pack(fill="x")
        self.host_box = tk.Frame(self.mode_box, bg=PANEL)
        self._note(self.host_box, tr("note.host"))
        self.koth_box = tk.Frame(self.mode_box, bg=PANEL)
        Segmented(self.koth_box, [('casual', tr('nav.casual')), ('official', tr('koth.official'))],
                  self.koth_category, lambda: self.koth_panel.render_events()).pack(fill='x', pady=(8, 0))
        self.koth_hint = tk.Label(self.koth_box, text=tr('koth.pick'), bg=PANEL, fg=TEXT, wraplength=300,
                                  justify='left', anchor='w', font=('Segoe UI', 10, 'bold'))
        self.koth_hint.pack(fill='x', pady=(8, 0))
        self._note(self.koth_box, tr('koth.join_hint'))
        self.tournament_box = tk.Frame(self.mode_box, bg=PANEL)

        self.match_divider = tk.Frame(inner, bg=BORDER, height=1)
        self.match_divider.pack(fill="x", pady=(14, 12))

        self.play_actions = tk.Frame(inner, bg=PANEL)
        self.play_actions.pack(fill="x")
        self.start_btn = PillButton(self.play_actions, text=tr("btn.start_host"), style="Accent.TButton", command=self.start)
        self.start_btn.pack(fill="x", pady=(0, 6))
        self.stop_btn = PillButton(self.play_actions, text=tr("btn.stop"), style="Danger.TButton", command=self.stop,
                                   state="disabled")
        self.stop_btn.pack(fill="x")
        self.hill_btn = PillButton(self.play_actions, text=tr("koth.manual"), command=self.hill)
        self.hill_btn.pack(fill="x", pady=(6, 0))

        # PREPARAR PARTIDA e Ferramentas: so para o dono (ver _sync_admin)
        self.admin_box = tk.Frame(inner, bg=PANEL)
        self.prepare_btn = PillButton(self.admin_box, text=tr("btn.prepare"), command=self.prepare)
        self.prepare_btn.pack(fill="x", pady=(6, 0))
        self.tools_open = False
        self.tools_toggle = tk.Label(self.admin_box, text="▸ " + tr("tools"), bg=PANEL, fg=ACCENT,
                                     font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.tools_toggle.pack(anchor="w", pady=(11, 0))
        self.tools_toggle.bind("<Button-1>", lambda _e: self._toggle_tools())
        self.tools = tk.Frame(self.admin_box, bg=PANEL)
        self.load_btn = PillButton(self.tools, text=tr("btn.load"), command=self.load_state)
        self.load_btn.pack(fill="x", pady=(8, 6))
        row = tk.Frame(self.tools, bg=PANEL)
        row.pack(fill="x", pady=(0, 6))
        self.solo_btn = PillButton(row, text=tr("btn.solo"), command=self.solo)
        self.solo_btn.pack(side="left")
        ctl = Segmented(row, [("p1", "P1"), ("p2", "P2"), ("both", "BOTH")], self.v["control"])
        ctl.configure(width=170, height=Segmented.HEIGHT)
        ctl.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.pine_btn = PillButton(self.tools, text=tr("btn.pine"), command=self.test_pine)
        self.pine_btn.pack(fill="x", pady=(0, 6))
        self.release_btn = PillButton(self.tools, text=tr("btn.release"), command=self.release_game)
        self.release_btn.pack(fill="x")
        self._note(self.tools, tr("note.tools"))

    def _sync_admin(self):
        # o servidor decide quem e o dono (campo admin da conta); aqui o bloco so aparece/some
        if not hasattr(self, "admin_box"):
            return
        if self.backend.is_admin():
            self.admin_box.pack(fill="x")
        else:
            self.admin_box.pack_forget()

    def _toggle_tools(self):
        self.tools_open = not self.tools_open
        self.tools_toggle.configure(text=("▾ " if self.tools_open else "▸ ") + tr("tools"))
        (self.tools.pack(fill="x") if self.tools_open else self.tools.pack_forget())

    def _rooms_panel(self, parent):
        """As salas: o painel principal da janela (ocupa todo o espaco livre da coluna direita)."""
        panel = RoundFrame(parent, radius=20, padx=16, pady=14, grow=True)
        self.rooms_panel = panel
        panel.pack(side="top", fill="both", expand=True, pady=(0, 13))
        inner = panel.inner

        top = tk.Frame(inner, bg=PANEL)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=tr("rooms.title"), bg=PANEL, fg=TEXT, font=("Segoe UI", 14, "bold")).pack(side="left")
        self.zt_room_actions = tk.Frame(top, bg=PANEL)
        self.zt_ip_button = PillButton(self.zt_room_actions, text=tr("rooms.zt_by_ip"), style="Small.TButton",
                                       command=self._join_zerotier_ip)
        self.zt_ip_button.pack(side="right")
        PillButton(self.zt_room_actions, text=tr("koth.refresh"), style="Small.TButton",
                   command=self._refresh_zerotier_rooms).pack(side="right", padx=(0, 6))
        self.rooms_status = tk.Label(top, text="", bg=PANEL, fg=DIM, font=("Segoe UI", 9), anchor="e",
                                     justify="right")
        self.rooms_status.pack(side="right")

        wrap = tk.Frame(inner, bg=PANEL)
        wrap.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical")
        cols = (("guest", tr("col.guest"), 200, 150), ("ping", tr("col.ping"), 76, 70),
                ("status", tr("col.status"), 120, 110), ("time", tr("col.time"), 64, 60),
                ("game", tr("col.game"), 64, 56))
        self.rooms_tree = ttk.Treeview(wrap, columns=[c[0] for c in cols], show="tree headings", height=8,
                                       selectmode="browse",
                                       yscrollcommand=lambda lo, hi: self._rooms_scrolled(sb, lo, hi))
        sb.configure(command=self.rooms_tree.yview)
        self.rooms_tree.heading("#0", text=tr("col.host"), anchor="w")   # a coluna #0 leva o avatar + o nome do host
        self.rooms_tree.column("#0", width=230, anchor="w", stretch=True)
        for key, text, width, minw in cols:
            self.rooms_tree.heading(key, text=text, anchor="w")
            self.rooms_tree.column(key, width=width, minwidth=minw, anchor="w", stretch=False)
        sb.pack(side="right", fill="y")
        self.rooms_tree.pack(side="left", fill="both", expand=True)
        self.rooms_preview = self._tree_preview(self.rooms_tree)
        self.rooms_tree.bind("<<TreeviewSelect>>", lambda _e: self.pick_room())
        for ev in ("<<TreeviewSelect>>", "<Configure>", "<B1-Motion>", "<ButtonRelease-1>"):
            self.rooms_tree.bind(ev, lambda _e: self.after_idle(self._place_guest_avs), add="+")

        footer = tk.Frame(inner, bg=PANEL)
        footer.pack(fill="x", pady=(8, 0))
        self.rooms_hint = tk.Label(footer, bg=PANEL, fg=DIM, font=("Segoe UI", 8),
                                   anchor="w", justify="left", wraplength=380)
        self.rooms_hint.pack(side="left", fill="x", expand=True)
        self.join_btn = PillButton(footer, text=tr("rooms.join"), style="Small.TButton",
                                   command=lambda: self.start("guest"), state="disabled")
        self.join_btn.pack(side="right")

    def open_console(self):
        if self.console_window is not None:
            self.console_window.deiconify()
            self.console_window.lift()
            return
        window = self.console_window = tk.Toplevel(self, bg=BG)
        window.title(tr("menu.logs"))
        window.geometry("720x360")
        window.minsize(460, 200)
        window.protocol("WM_DELETE_WINDOW", self._close_console)

        panel = RoundFrame(window, radius=18, padx=14, pady=10)
        panel.pack(fill="both", expand=True, padx=10, pady=10)
        inner = panel.inner
        top = tk.Frame(inner, bg=PANEL)
        top.pack(fill="x", pady=(0, 6))
        PillButton(top, text=tr("btn.clear"), style="Small.TButton", command=self.clear).pack(side="right")
        PillButton(top, text=tr("btn.copy"), style="Small.TButton", command=self.copy_console).pack(side="right",
                                                                                                   padx=(0, 6))
        PillButton(top, text=tr("btn.copy_cmd"), style="Small.TButton", command=self.copy_command).pack(
            side="right", padx=(0, 6))
        self.console_status = tk.Label(inner, anchor='w', bg=PANEL, font=('Segoe UI', 9, 'bold'))
        self.console_status.pack(fill='x', pady=(0, 4))
        box = RoundFrame(inner, fill="#070a10", border=BORDER, radius=12, padx=6, pady=6, bg=PANEL)
        box.pack(fill="both", expand=True)
        wrap = box.inner
        sb = ttk.Scrollbar(wrap, orient="vertical")
        self.console = tk.Text(wrap, bg="#070a10", fg="#c8d6ea", insertbackground=TEXT, selectbackground="#2a4a72",
                               relief="flat", wrap="word", font=("Cascadia Mono", 8), padx=8, pady=4, height=7,
                               state="disabled", yscrollcommand=sb.set, highlightthickness=0, bd=0)
        sb.configure(command=self.console.yview)
        sb.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)
        for tag, color in (("error", "#ff8497"), ("success", "#62e2ac"), ("info", "#80b9ff"), ("warn", WARN),
                           ("dim", DIM)):
            self.console.tag_configure(tag, foreground=color)
        self._set_status(self.status_key, self.status_color)
        for text, tag in self._history:
            self._write(text, tag)

    def _close_console(self):
        self.console_window.destroy()
        self.console_window = self.console = self.console_status = None

    # ================================================================ dicas
    def _nick_hint(self):
        acc = self.backend.account
        if acc:
            shown = core.account_game_nick(acc)
            self.nick_hint.configure(text=acc["nick"], fg=TEXT)
            self.nick_sub.configure(text=tr("nick.sub_game", shown=shown) if shown else tr("nick.sub_default"))
        else:
            self.nick_hint.configure(text=tr("nick.none"), fg=MUTED)
            self.nick_sub.configure(text=tr("nick.none_sub"))

    def _select_section(self):
        section = self.section.get()
        mode = 'host' if section == 'casual' else section
        self.v['mode'].set(mode)
        self._sync_mode()

    def _change_transport(self):
        self.rooms_tree.selection_remove(*self.rooms_tree.selection())
        self._sync_mode()
        self._rooms_refresh()

    def _sync_mode(self):
        if self._koth_pending or (self.backend.running and self.backend.session_role == 'hill'):
            self.v['mode'].set('koth')
        mode = self.v['mode'].get()
        casual = mode in ('host', 'guest')
        self.section.set('casual' if casual else mode)
        if casual:
            self.casual_box.pack(fill='x', before=self.match_divider)
        else:
            self.casual_box.pack_forget()
        direct = casual and self.casual_transport.get() == 'zerotier'
        if casual and not direct:
            self.host_box.pack(fill='x')
        else:
            self.host_box.pack_forget()
        if mode == 'koth':
            self.koth_box.pack(fill='x')
        else:
            self.koth_box.pack_forget()
        if mode == 'tournaments':
            self.tournament_box.pack(fill='x')
        else:
            self.tournament_box.pack_forget()
        if direct:
            self.mode_box.pack_forget()
        else:
            self.mode_box.pack(fill='x', before=self.match_divider)
        for button in (self.start_btn, self.hill_btn):
            button.pack_forget()
        self._show_stop()
        if mode != 'tournaments':
            self.start_btn.pack(fill='x', before=self.stop_btn, pady=(0, 6))
        if mode == 'koth':
            self.hill_btn.pack(fill='x', pady=(6, 0))
        if mode == 'tournaments':
            self.tournaments.actions.pack(fill='x')
        else:
            self.tournaments.actions.pack_forget()
        panel = self.rooms_panel if casual else self.koth_panel if mode == 'koth' else self.tournaments
        for other in (self.rooms_panel, self.koth_panel, self.tournaments):
            if other != panel:
                other.pack_forget()
        panel.pack(side='top', fill='both', expand=True, pady=(0, 13))
        if not casual:
            panel.refresh()
        self.start_btn.configure(text=tr('koth.join' if mode == 'koth' else 'nav.zt_host' if direct else 'nav.net_host'))
        self.rooms_hint.configure(text=tr('rooms.zt_hint' if direct else 'rooms.join_hint'))
        if direct:
            self.zt_room_actions.pack(side="right", before=self.rooms_status, padx=(10, 0))
        else:
            self.zt_room_actions.pack_forget()
            self._close_zerotier_rooms()
        self._sync_pvp_state_picker()

    def _sync_pvp_state_picker(self, _event=None):
        if (self.section.get() == "casual" and self.casual_transport.get() == "zerotier"
                and self.v["pvp_game"].get() == "UN6"):
            self.zt_states.pack(fill="x", pady=(8, 0))
        else:
            self.zt_states.pack_forget()

    def _show_stop(self):
        if self.section.get() == 'tournaments' and not self.backend.running:
            self.stop_btn.pack_forget()
        elif not self.stop_btn.winfo_manager():
            self.stop_btn.pack(fill='x')

    def _detect_game(self):
        """Le o CRC do jogo aberto no PCSX2 (PINE). Retorna "un5" / "un6", ou None (o aviso ja foi mostrado)."""
        try:
            game, crc = core.detect_game(core.FIXED["pine_slot"])
        except Exception as exc:                          # noqa: BLE001 - PCSX2 fechado, PINE desligado, etc.
            self._log(tr("log.game_pine", exc=exc), "error")
            messagebox.showerror(tr("dlg.game_title"), tr("dlg.game_pine", exc=exc))
            return None
        if game is None:
            self._log(tr("log.game_unknown", crc=crc or "?"), "error")
            messagebox.showerror(tr("dlg.game_title"),
                                 tr("dlg.game_unknown", crc=crc or "?", un5=core.UN5_CRC, un6=core.UN6_CRC))
            return None
        self._log(tr("log.game_ok", game=game.upper(), crc=crc), "info")
        return game

    def _pick_game(self) -> bool:
        """Detecta o jogo e guarda em self.game (usado por cfg(): save state e symbols de cada jogo)."""
        game = self._detect_game()
        if game is None:
            return False
        self.game = game
        return True

    def _ensure_state_dir(self) -> bool:
        """A pasta de save do PCSX2 e achada sozinha. So se isso falhar o launcher pergunta (uma vez, fica salva)."""
        if Path(self.cfg()["state_dir"] or "?").is_dir():
            return True
        messagebox.showinfo(tr("dlg.sstates_title"), tr("dlg.sstates_body"))
        path = filedialog.askdirectory(title=tr("dlg.sstates_pick"), initialdir=str(Path.home()))
        if not path:
            return False
        self.v["state_dir"].set(path)
        return True

    # ================================================================ salas
    def _avatar_image(self, url):
        """PhotoImage do avatar (baixado em segundo plano pelo backend) ou um espaco transparente enquanto isso."""
        img = self._avimgs.get(url)
        if img is not None:
            return img
        if url:
            img = make_avatar(self.backend.avatar_for(url))
            if img is not None:
                self._avimgs[url] = img
                return img
        return self.blank_av

    def _room_row(self, r):
        """(nome do host, avatar, valores das demais colunas, tag de cor) de uma sala."""
        players = r.get("players") or {}
        host = players.get("host") or {}
        guest = players.get("guest") or {}
        playing = r.get("status") == "playing"
        if playing:
            phase_key = "phase." + str(r.get("phase"))
            status = tr(phase_key) if has(phase_key) else tr("room.in_match")
        else:
            status = tr("room.open")
        ping = r.get("ping")
        ping_txt = f"{ping} ms" if (playing and ping is not None) else "—"
        elapsed = r.get("elapsed")
        if playing and elapsed is not None:               # o servidor manda o tempo no instante da resposta
            s = int(elapsed + time.monotonic() - r.get("fetched", time.monotonic()))
            time_txt = f"{s // 60:02d}:{s % 60:02d}"
        else:
            time_txt = "—"
        values = (GUEST_PAD + (guest.get("nick") or "—"), ping_txt, status.upper(), time_txt,
                  str(r.get("game") or "—").upper())
        return (host.get("nick") or r.get("nick") or "?", self._avatar_image(host.get("avatar_url")), values, ())

    def _guest_img(self, r):
        """Avatar do guest da sala, ou None se a sala nao tem guest."""
        guest = (r.get("players") or {}).get("guest") or {}
        if not guest.get("nick"):
            return None
        return self._avatar_image(guest.get("avatar_url"))

    def _rooms_scrolled(self, sb, lo, hi):
        sb.set(lo, hi)
        self.after_idle(self._place_guest_avs)
        self.after_idle(self._sync_rooms_preview)

    def _place_guest_avs(self):
        """O Treeview so mostra imagem na coluna #0: o avatar do guest e um Label colocado sobre a celula GUEST
        (o texto da celula tem um recuo para deixar o espaco do avatar)."""
        tree = self.rooms_tree
        style = ttk.Style(self)
        normal = style.lookup("Treeview", "background") or PANEL
        picked = style.lookup("Treeview", "background", ("selected",)) or normal
        selected = set(tree.selection())
        height = tree.winfo_height()
        for iid, img in self.guest_imgs.items():
            box = tree.bbox(iid, "guest") if (img is not None and tree.exists(iid)) else ""
            lab = self.guest_labels.get(iid)
            if not box or box[1] + box[3] > height:
                if lab is not None:
                    lab.place_forget()
                continue
            x, y, _w, h = box
            if lab is None:
                lab = tk.Label(tree, bd=0, highlightthickness=0)
                lab.bind("<Button-1>", lambda _e, i=iid: tree.selection_set(i))
                self.guest_labels[iid] = lab
            lab.configure(image=img, bg=picked if iid in selected else normal)
            lab.image = img
            lab.place(x=x + 4, y=y + max(0, (h - ROW_AV) // 2))
        for iid in [i for i in self.guest_labels if i not in self.guest_imgs]:
            self.guest_labels.pop(iid).destroy()

    def _rooms_tick(self):
        try:
            self._rooms_refresh()
        except Exception as exc:                          # noqa: BLE001 - a lista nunca derruba o loop
            self._log(tr("log.rooms_err", exc=exc), "error")
        finally:
            self.after(500, self._rooms_tick)

    def _sync_rooms_preview(self):
        self._sync_tree_preview(self.rooms_preview, self.rooms_tree)

    @staticmethod
    def _tree_preview(tree):
        preview = tk.Label(tree.master, bg=PANEL, bd=0, highlightthickness=0)
        preview.artwork = None
        preview.bind("<MouseWheel>", lambda event: tree.event_generate(
            "<MouseWheel>", delta=event.delta, state=event.state))
        for button in (4, 5):
            sequence = f"<Button-{button}>"
            preview.bind(sequence, lambda _event, seq=sequence: tree.event_generate(seq))
        return preview

    def _sync_tree_preview(self, preview, tree):
        if not self.v["show_background"].get() or preview.artwork is None:
            preview.place_forget()
            return
        artwork = preview.artwork
        rows = tree.get_children()
        if rows:
            last = tree.bbox(rows[-1])
            if not last or last[1] + last[3] >= tree.winfo_height():
                preview.place_forget()
                return
            x = tree.winfo_x()
            top = tree.winfo_y() + last[1] + last[3]
            right = min(artwork.width, x + tree.winfo_width())
            bottom = min(artwork.height, tree.winfo_y() + tree.winfo_height())
        else:
            x, top, right, bottom = 0, 0, artwork.width, artwork.height
        if right <= x or bottom <= top:
            preview.place_forget()
            return
        bounds = (x, top, right, bottom)
        if preview.bounds != bounds:
            preview.background_image = ImageTk.PhotoImage(artwork.crop(bounds), master=preview)
            preview.configure(image=preview.background_image)
            preview.bounds = bounds
        preview.place(x=x, y=top, width=right - x, height=bottom - top)
        preview.lift()

    def _rooms_refresh(self):
        if self.v['mode'].get() == 'koth':
            self.koth_panel.tick()
            return
        if self.section.get() == 'tournaments':
            return
        direct = self.casual_transport.get() == 'zerotier'
        if direct:
            address = self.v['zerotier_address'].get().strip()
            found, error = self._local_rooms(address)
        else:
            self.backend.poll_rooms()
            found, error = self.backend.online_rooms, self.backend.online_error
        self.rooms_data = {r["id"]: r for r in found}
        ids = [r["id"] for r in found]
        tree = self.rooms_tree
        if ids != list(tree.get_children()):              # so reconstroi se o conjunto de salas mudou
            selected = tree.selection()
            tree.delete(*tree.get_children())
            for r in found:
                tree.insert("", "end", iid=r["id"], text="")
            if selected and selected[0] in self.rooms_data:
                tree.selection_set(selected[0])
        for r in found:                                   # atualiza no lugar: nao pisca nem perde a selecao
            name, img, values, tags = self._room_row(r)
            tree.item(r["id"], text="  " + name, image=img, values=values, tags=tags)
        self.guest_imgs = {r["id"]: self._guest_img(r) for r in found}
        self._place_guest_avs()
        if error:
            text = tr("rooms.server_err", err=error)
        elif found:
            text = tr("rooms.count", n=len(found))
        else:
            text = tr("rooms.zt_no_address" if direct and not address else "rooms.zt_none" if direct else "rooms.none")
        self.rooms_status.configure(text=text, fg=RED if error else DIM)
        self._sync_rooms_preview()
        self.pick_room()

    def _local_rooms(self, address):
        if not address:
            return [], None
        if self.zerotier_rooms is not None and self.zerotier_rooms.zerotier_address != address:
            self._close_zerotier_rooms()
        if self.zerotier_rooms is None:
            self.zerotier_rooms = RoomListener(zerotier_address=address)
        rooms = self.zerotier_rooms.poll()
        return [
            {**room, 'id': f"zt:{room['ip']}:{room['port']}", 'is_local': room['ip'] == address}
            for room in rooms
            if room.get('game') and room['port'] == int(core.HOST_PORT)
            and (self.backend.running if room['ip'] == address else uses_interface(room['ip'], address))
        ], self.zerotier_rooms.error

    def _close_zerotier_rooms(self):
        if self.zerotier_rooms is not None:
            self.zerotier_rooms.close()
            self.zerotier_rooms = None

    def _refresh_zerotier_rooms(self):
        if self.zerotier_rooms is not None and self.zerotier_rooms.error:
            self._close_zerotier_rooms()
        self._rooms_refresh()

    def _join_zerotier_ip(self):
        local_address = self._saved_zerotier_address()
        if not local_address:
            return
        prefix = local_address.rsplit(".", 1)[0] + "."
        previous = self.v["zerotier_host"].get()
        remembered = previous[len(prefix):] if previous.startswith(prefix) else previous
        address = simpledialog.askstring(tr("rooms.zt_by_ip"), tr("rooms.zt_host_ip", prefix=prefix),
                                         parent=self, initialvalue=remembered)
        if address is not None:
            address = address.strip()
            self.start("guest", host_ip=prefix + address if address and "." not in address else address)

    def pick_room(self):
        busy = self.backend.running or self._after_sync or self._after_allow or self._koth_pending
        self.zt_ip_button.configure(state="disabled" if busy else "normal")
        self.join_btn.configure(state="normal" if not busy and self._picked_room() else "disabled")

    def _picked_room(self):
        """The open room the player can join, or None."""
        selected = self.rooms_tree.selection()
        room = self.rooms_data.get(selected[0]) if selected else None
        return room if room and room["status"] == "waiting" and not room.get("is_local") else None

    # ================================================================ console / status
    def _write(self, text, tag=None):
        if self.console_window is None:
            return
        self.console.configure(state="normal")
        self.console.insert("end", text.rstrip() + "\n", tag or ())
        self.console.see("end")
        self.console.configure(state="disabled")

    def _log(self, text, tag=None):
        self._history.append((text, tag))
        if len(self._history) > 2000:
            del self._history[:500]
        self._write(text, tag)

    def clear(self):
        self._history.clear()
        if self.console_window is None:
            return
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _clip(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def copy_console(self):
        if self.console_window is not None:
            self._clip(self.console.get("1.0", "end"))

    def copy_command(self):
        self._clip(self.backend.last_cmd or tr("log.nothing_run"))

    def _set_status(self, text, color):
        """`text` e a chave do status (READY, IN MATCH, ...); o rotulo mostrado vem do idioma atual."""
        color = COLORS.get(color, color)                  # aceita nome do backend ou hex
        self.status_key, self.status_color = text, color
        key = "st." + text
        if self.console_window is not None:
            self.console_status.configure(text=tr(key), fg=color)

    def _set_buttons(self, running):
        self._show_stop()
        self.tournaments.sync_connect()
        running = running or self._koth_pending
        state = "disabled" if running else "normal"
        for b in (self.load_btn, self.start_btn, self.solo_btn, self.pine_btn, self.release_btn, self.hill_btn):
            b.configure(state=state)
        self.join_btn.configure(state="normal" if not running and self._picked_room() else "disabled")
        self.zt_ip_button.configure(state=state)
        self.pvp_game_picker.configure(state="disabled" if running else "readonly")
        self.zt_state_picker.configure(state=state)
        # PREPARE: so o dono (o servidor decide quem e o dono; o launcher so esconde o botao)
        self.prepare_btn.configure(state="normal" if (not running and self.backend.is_admin()) else "disabled")
        self.stop_btn.configure(state="normal" if running and not self._koth_pending else "disabled")

    # ================================================================ acoes
    def _spawn(self, args, label, allow_missing_symbols=False, session_env=None, *, cfg=None):
        try:
            self.backend.spawn(cfg if cfg is not None else self.cfg(), args, allow_missing_symbols,
                               session_env=session_env)
        except RuntimeError as exc:
            return messagebox.showwarning(tr("dlg.busy"), str(exc))
        except ValueError as exc:
            return messagebox.showerror(tr("dlg.cannot_start"), str(exc))
        except OSError as exc:
            return self._log(tr("log.could_not_launch", exc=exc), "error")
        self._log(f"\n▶ {label}", "info")
        self._set_status("STARTING", BLUE)
        self._set_buttons(True)

    def _args(self, action, state=None):
        try:
            return core.make_args(self.cfg(), action, state)
        except ValueError as exc:
            messagebox.showerror(tr("dlg.cannot_continue"), str(exc))
            return None

    def _zerotier_picker(self, dialog, initial, address_var=None):
        from zerotier_networks import discover
        tk.Label(dialog, text=tr("hill.address"), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(8, 3))
        selected_network = tk.StringVar(value=initial)
        networks = {}
        disabled_label = tr('hill.zt.choose')
        network_box = ttk.Combobox(dialog, textvariable=selected_network, width=65, values=(disabled_label,))
        network_box.pack(fill='x')
        if selected_network.get() == '0.0.0.0':
            selected_network.set(disabled_label)
        network_status = tk.Label(dialog, text='', bg=PANEL, fg=MUTED, wraplength=480, justify='left')
        network_status.pack(anchor='w', pady=(4, 0))
        network_controls = tk.Frame(dialog, bg=PANEL)
        network_controls.pack(fill='x', pady=(6, 0))
        scan_results = queue.Queue()
        scan_buttons = []
        scan_job = [None]

        def cancel_scan_poll(event):
            if event.widget is dialog and scan_job[0] is not None:
                dialog.after_cancel(scan_job[0])
                scan_job[0] = None

        dialog.bind('<Destroy>', cancel_scan_poll, add='+')

        def address_for(choice):
            if choice == disabled_label:
                return '0.0.0.0'
            return networks.get(choice, choice).strip() or '0.0.0.0'

        if address_var is None:
            address_var = tk.StringVar()
        tk.Label(dialog, text=tr('zt.selected_ip'), bg=PANEL, fg=TEXT).pack(anchor='w', pady=(8, 3))
        ttk.Entry(dialog, textvariable=address_var, state='readonly').pack(fill='x')

        def update_address(*_):
            import ipaddress
            try:
                address = ipaddress.IPv4Address(address_for(selected_network.get()))
                address_var.set('' if address.is_unspecified else str(address))
            except ValueError:
                address_var.set('')

        selected_network.trace_add('write', update_address)
        update_address()

        def refresh_networks(allow_admin=False):
            initial_choice = selected_network.get()
            previous_address = address_for(initial_choice)
            network_status.configure(text=tr('hill.zt.scanning'))
            for button in scan_buttons:
                button.configure(state='disabled')

            def work():
                try:
                    scan_results.put(discover(allow_admin=allow_admin,
                                              cache_path=core.DATA_DIR / 'zerotier-networks.json'))
                except Exception:
                    scan_results.put(([], 'hill.zt.unavailable'))

            def poll():
                scan_job[0] = None
                if not dialog.winfo_exists():
                    return
                try:
                    choices, status = scan_results.get_nowait()
                except queue.Empty:
                    scan_job[0] = dialog.after(100, poll)
                    return
                labels = {}
                current_choice = selected_network.get()
                current_address = address_for(current_choice)
                was_detected = current_choice in networks
                for choice in choices:
                    label = f"{choice['name']} — {choice['address']}"
                    if label in labels:
                        label += f" ({choice['id']})"
                    labels[label] = choice['address']
                networks.clear()
                networks.update(labels)
                network_box.configure(values=(disabled_label, *labels))
                if selected_network.get() == initial_choice:
                    matching = next((label for label, ip in labels.items() if ip == previous_address), None)
                    if matching:
                        selected_network.set(matching)
                    elif previous_address == '0.0.0.0' and len(labels) == 1:
                        selected_network.set(next(iter(labels)))
                    else:
                        selected_network.set(disabled_label if previous_address == '0.0.0.0' else previous_address)
                elif was_detected:
                    matching = next((label for label, ip in labels.items() if ip == current_address), None)
                    selected_network.set(matching or current_address)
                network_status.configure(text=tr(status))
                for button in scan_buttons:
                    button.configure(state='normal')

            threading.Thread(target=work, daemon=True).start()
            scan_job[0] = dialog.after(100, poll)

        scan_buttons.append(ttk.Button(network_controls, text=tr('hill.zt.refresh'), command=refresh_networks))
        scan_buttons[0].pack(side='left')
        if os.name != 'nt' and shutil.which('pkexec'):
            button = ttk.Button(network_controls, text=tr('hill.zt.names'), command=lambda: refresh_networks(True))
            button.pack(side='left', padx=(8, 0))
            scan_buttons.append(button)
        scan_job[0] = dialog.after(0, refresh_networks)
        return lambda: address_for(selected_network.get())

    def configure_zerotier(self):
        parent = self.dialog or self
        dialog = tk.Toplevel(parent, bg=PANEL, padx=20, pady=16)
        dialog.title(tr('zt.settings'))
        dialog.transient(parent)
        get_address = self._zerotier_picker(dialog, self.v['zerotier_address'].get())

        def save():
            address = get_address()
            if address != '0.0.0.0':
                try:
                    core.zerotier_args({'zerotier_address': address}, 'host')
                except ValueError as error:
                    return messagebox.showerror(tr('zt.settings'), str(error), parent=dialog)
            self.v['zerotier_address'].set('' if address == '0.0.0.0' else address)
            core.save_config({**self.raw(), 'ignore_desync': False})
            self._close_zerotier_rooms()
            self._rooms_refresh()
            dialog.destroy()

        PillButton(dialog, text=tr('zt.save'), command=save).pack(fill='x', pady=(12, 0))
        dialog.grab_set()

    def _saved_zerotier_address(self):
        address = self.v['zerotier_address'].get().strip()
        try:
            core.zerotier_args({'zerotier_address': address}, 'host')
        except ValueError:
            messagebox.showinfo(tr('zt.settings'), tr('rooms.zt_no_address'), parent=self)
            return None
        return address

    def zerotier(self, *, fixture, round_robin=False):
        if self.backend.running or self._koth_pending or self._after_sync or self._after_allow:
            return
        address = self._saved_zerotier_address()
        if not address or not self._ensure_state_dir() or not self._pick_game():
            return
        match = KOTH_STATES.get(fixture.get('match_state'))
        if match and match[0] != self.game:
            return messagebox.showerror(tr('zt.title'),
                                        tr('dlg.game_mismatch', room=match[0].upper(), mine=self.game.upper()))
        role = 'host' if fixture['role'] == 'p1' else 'guest'
        title = tr('bracket.match_role', p1=fixture['p1']['name'], p2=fixture['p2']['name'],
                   role=fixture['role'].upper())
        cfg = {**self.cfg(), 'transport': 'zerotier', 'zerotier_address': address,
               'fixture': fixture, 'game': self.game, 'hill_url': self.tournaments.url,
               'round_robin': round_robin}
        if match:
            cfg['zerotier_state'] = match[1]
        self._start_direct(cfg, role, title, fixture_login=self.backend.session)

    def _start_direct(self, cfg, role, title, *, fixture_login=None, announced_tag=None):
        def launch():
            if cfg.get('fixture') and self.backend.session != fixture_login:
                self._log(tr('bracket.login'), 'error')
                self._set_status('READY', MUTED)
                return
            try:
                args = core.make_args(cfg, role, cfg['state_file'])
            except ValueError as error:
                self._set_status('READY', MUTED)
                return messagebox.showerror(tr('zt.title'), str(error))
            session = fixture_login if cfg.get('fixture') else self.backend.session
            env_key = 'UN5_FIXTURE_LOGIN' if cfg.get('fixture') else 'UN5_SCOREBOARD_SESSION'
            spawn_cfg = {**cfg, 'zerotier_host': self.v['zerotier_host'].get()}
            self._spawn(args, title, session_env={env_key: session} if session else None, cfg=spawn_cfg)

        if cfg.get('fixture'):
            sync = (lambda: self.backend.sync_zerotier_state(cfg, 'host')) if cfg['fixture'].get('match_state') else None
            self._sync_for_match(launch, sync=sync)
        else:
            self._sync_for_match(launch, sync=lambda: self.backend.sync_zerotier_state(cfg, role, announced_tag))

    def watch_hill(self):
        event = self.koth_panel.selected_event()
        if event is None:
            return messagebox.showinfo(tr('hill.title'), tr('koth.pick'))
        if not self.backend.session:
            return messagebox.showinfo(tr('hill.title'), tr('koth.casual_login'))
        return self.hill(event, observe=True)

    def hill(self, event=None, *, observe=False):
        if self.backend.running or self._koth_pending or self._after_sync or self._after_allow or self.koth_panel.leave_busy:
            return
        if not self._ensure_state_dir() or not self._pick_game():
            return
        expected = KOTH_STATES.get((event or {}).get('match_state'))
        if expected and expected[0] != self.game:
            return messagebox.showerror(tr('hill.title'),
                                        tr('dlg.game_mismatch', room=expected[0].upper(), mine=self.game.upper()))
        ticket = self.v['hill_ticket'].get().strip()
        if observe:
            return self._join_hill(DEFAULT_URL, '0.0.0.0', ticket, event, observe=True)

        dialog = tk.Toplevel(self, bg=PANEL, padx=20, pady=16)
        dialog.title(tr('hill.title'))
        dialog.transient(self)

        def field(label, initial, *, secret=False):
            tk.Label(dialog, text=tr(label), bg=PANEL, fg=TEXT).pack(anchor='w', pady=(8, 3))
            value = tk.StringVar(master=dialog, value=initial)
            ttk.Entry(dialog, textvariable=value, width=65, show='*' if secret else '').pack(fill='x')
            return value

        if event:
            tk.Label(dialog, text=event['name'], bg=PANEL, fg=ACCENT,
                     font=('Segoe UI', 12, 'bold')).pack(anchor='w')
            entry = 'koth.linked_entry' if self.backend.session else 'koth.guest_entry'
            tk.Label(dialog, text=tr(entry), bg=PANEL, fg=MUTED,
                     wraplength=480, justify='left').pack(anchor='w', pady=(6, 0))
            name_field = field('koth.player_name', self.v['hill_player_name'].get() or self.cfg().get('nick', ''))
        else:
            ticket_field = field('hill.ticket', ticket, secret=True)

        tk.Label(dialog, text=tr('hill.transport'), bg=PANEL, fg=TEXT).pack(anchor='w', pady=(8, 3))
        network = ttk.Combobox(dialog, values=('ZeroTier', 'Netplay'), state='readonly')
        network.set('Netplay' if self.v['hill_transport'].get() == 'relay' else 'ZeroTier')
        network.pack(fill='x')
        Switch(dialog, tr('hill.spectators'), self.v['hill_spectators']).pack(anchor='w', pady=(10, 0))
        if event and self.backend.session:
            tk.Label(dialog, text=tr('koth.address_rule'), bg=PANEL, fg=MUTED,
                     wraplength=480, justify='left').pack(anchor='w', pady=(0, 8))

        def connect():
            try:
                code = ticket if event else ticket_field.get().strip()
                name = name_field.get().strip() if event else ''
                if event and not name:
                    raise ValueError(tr('koth.player_name'))
                if not event and not code:
                    raise ValueError(tr('hill.ticket'))
            except ValueError as error:
                return messagebox.showerror(tr('hill.title'), str(error), parent=dialog)
            if name:
                self.v['hill_player_name'].set(name)
            transport = 'relay' if network.get() == 'Netplay' else 'zerotier'
            address = '0.0.0.0' if transport == 'relay' else self._saved_zerotier_address()
            if not address:
                return
            self.v['hill_transport'].set(transport)
            dialog.destroy()
            self._join_hill(DEFAULT_URL, address, code, event, name=name, transport=transport)

        ttk.Button(dialog, text=tr('hill.connect'), command=connect).pack(fill='x', pady=(8, 0))
        dialog.grab_set()

    def _join_hill(self, url, address, ticket, event, *, name='', observe=False, transport='zerotier'):
        self.v['hill_url'].set(url)
        core.save_config({**self.raw(), 'ignore_desync': False})
        netplay_session = self.backend.session
        if event:
            self._koth_pending = True
            self.koth_live_event = event
            self.v['mode'].set('koth')
            self._sync_mode()
            self._set_buttons(True)
            self.stop_btn.configure(state='disabled')
            self.koth_panel.display(event, reason=tr('koth.loading' if observe else 'koth.registering'))

            def enroll():
                from koth_client import MembershipStore, enroll as enroll_event, watch_ticket
                kind = 'koth_watch' if observe else 'koth_enroll'
                try:
                    if observe:
                        result = watch_ticket(url, netplay_session, event['id'])
                    else:
                        result = enroll_event(url, event, name, MembershipStore(core.DATA_DIR/'koth-memberships.json'), ticket,
                                              netplay_session=netplay_session, address=address if netplay_session and transport == 'zerotier' else '')
                    self.backend.q.put((kind, url, address, transport, result, ''))
                except Exception as error:
                    self.backend.q.put((kind, url, address, transport, None, str(error)))

            threading.Thread(target=enroll, daemon=True).start()
        else:
            self._koth_pending = True
            self._set_buttons(True)
            self.stop_btn.configure(state='disabled')

            def resolved(match_event, error):
                if error:
                    self._koth_pending = False
                    self._set_buttons(False)
                    return messagebox.showerror(tr('hill.title'), error)
                self._begin_hill(url, address, ticket, match_event, personal_code=True, transport=transport)

            self._window_task(self, lambda: event_for_ticket(url, ticket), resolved)

    def _begin_hill(self, url, address, ticket, event=None, *, observe=False, personal_code=False, transport='zerotier'):
        match = KOTH_STATES.get((event or {}).get('match_state'))
        if match and match[0] != self.game:
            self._koth_pending = False
            self._set_buttons(False)
            return messagebox.showerror(tr('hill.title'),
                                        tr('dlg.game_mismatch', room=match[0].upper(), mine=self.game.upper()))
        self.koth_live_ticket = '' if observe else ticket
        self.koth_observing = observe
        if not observe:
            self.v['hill_ticket'].set(ticket)
        self.v['hill_url'].set(url)
        if event:
            self.v['hill_event_id'].set(str(event['id']))
        self.koth_live_event = event
        self.koth_live_state = {}
        self._koth_pending = True
        self.v['mode'].set('koth')
        core.save_config({**self.raw(), 'ignore_desync': False})
        self._sync_mode()
        self._set_buttons(True)
        self.stop_btn.configure(state='disabled')
        self.koth_panel.display(event, reason=tr('koth.loading'))

        cfg = self.cfg()
        if match:
            cfg['zerotier_state'] = match[1]

        def launch():
            match_cfg = cfg if match else self.cfg()
            args = ['hill', '--api-url', url, '--address', address, '--game', self.game,
                    '--delay', core.MATCH_DELAY, '--auto-delay', '--transport', transport,
                    '--state', match_cfg['state_file'], '--state-dir', match_cfg['state_dir'], '--load-slot', match_cfg['load_slot'],
                    '--nick', match_cfg.get('nick', '')]
            if personal_code:
                args.append('--personal-code')
            if observe:
                args.append('--observe')
            elif not self.v['hill_spectators'].get():
                args.append('--no-spectators')
            self._koth_pending = False
            self._spawn(args, tr('hill.title'), session_env={'UN5_HILL_TICKET': ticket,
                        'UN5_NETPLAY_SESSION': '' if observe else self.backend.session}, cfg=match_cfg)
            self.koth_panel.display(event)

        self._after_sync = launch
        self._log('\n▶ '+tr('run.checking'), 'info')
        self._set_status('LOADING', BLUE)
        if match:
            self.backend.sync_zerotier_state(cfg, 'host')
        else:
            self.backend.sync_default(self.game)

    def prepare(self):
        if not self.backend.is_admin():
            return messagebox.showinfo(tr("dlg.prepare"), tr("dlg.prepare_owner"))
        if not self._ensure_state_dir():
            return
        if not self._pick_game():
            return
        args = self._args("prepare")
        if args:
            self._spawn(args, tr("run.prepare"))

    def load_state(self):
        if not self._ensure_state_dir():
            return
        if not self._pick_game():
            return
        args = self._args("load", self.cfg()["state_file"])
        if args:
            self._spawn(args, tr("run.load"))

    def start(self, role="host", *, host_ip=None):
        if self._koth_pending or self.backend.running or self._after_sync or self._after_allow:
            return
        section = self.section.get()
        direct = self.casual_transport.get() == 'zerotier'
        if host_ip is not None and (section != 'casual' or not direct or role != 'guest'):
            return
        if section == 'tournaments':
            return
        if section == 'koth':
            event = self.koth_panel.selected_event()
            if event is None:
                return messagebox.showinfo(tr('hill.title'), tr('koth.pick'))
            return self.hill(event)

        address = self.v["zerotier_address"].get().strip()
        if direct and not address:
            return messagebox.showinfo(tr('zt.settings'), tr('rooms.zt_no_address'))
        room = self._picked_room() if role == "guest" and host_ip is None else None
        if role == "guest" and room is None and host_ip is None:
            return messagebox.showinfo(tr("dlg.rooms"), tr("dlg.pick_room"))
        if direct:
            direct_settings = {'transport': 'zerotier', 'zerotier_address': address,
                               'zerotier_host': room['ip'] if room else host_ip or '',
                               'announce_zerotier': True, 'game': self.game}
            try:
                core.zerotier_args(direct_settings, role)
            except ValueError as error:
                return messagebox.showerror(tr('zt.settings'), str(error), parent=self)
            if host_ip is not None and host_ip != self.v["zerotier_host"].get():
                self.v["zerotier_host"].set(host_ip)
                core.save_config({**self.raw(), "ignore_desync": False})
        if not self._ensure_state_dir() or not self._pick_game():
            return
        room_game = room.get("game") if room else None
        expected_game = room_game if room_game in ("un5", "un6") else self.v["pvp_game"].get().lower()
        if expected_game != self.game:
            key = "dlg.game_mismatch" if room_game in ("un5", "un6") else "dlg.pvp_game_mismatch"
            return messagebox.showerror(tr("dlg.game_title"),
                                        tr(key, room=expected_game.upper(), mine=self.game.upper()))

        self.v["mode"].set(role)
        if direct:
            cfg = {**self.cfg(), **direct_settings, 'game': self.game}
            return self._start_direct(cfg, role, tr('zt.title'), announced_tag=room.get('tag') if room else None)

        self.v["room_id"].set(room["id"] if room else "")
        self._sync_for_match(lambda: self._launch(role), sync=lambda: self.backend.sync_default(self.game, relay=True))

    def _sync_for_match(self, launch, *, sync=None):
        self._after_sync = launch
        self._log("\n▶ " + tr("run.checking"), "info")
        self._set_status("LOADING", BLUE)
        self._set_buttons(True)
        self.stop_btn.configure(state="disabled")
        if sync is None:
            self.backend.sync_default(self.game)
        else:
            sync()

    def _launch(self, role):
        if role == "guest":                               # the server decides first (same IP / same account)
            self._log(tr("run.permission"), "info")
            self._set_status("LOADING", BLUE)
            self._set_buttons(True)
            self.stop_btn.configure(state="disabled")
            self._after_allow = lambda: self._launch_now(role)
            self.backend.check_join(self.v["room_id"].get())
            return
        self._launch_now(role)

    def _launch_now(self, role):
        cfg = self.cfg()
        try:
            args = core.make_args(cfg, role, cfg["state_file"])
        except ValueError as error:
            self._set_status("READY", MUTED)
            return messagebox.showerror(tr("dlg.cannot_continue"), str(error))
        label = tr("run.host") if role == "host" else tr("run.guest")
        if role == "host" and self.v["ignore_desync"].get():
            label += tr("run.ignore_on")
        # A sessao de Discord vai so para o placar (scoreboard.py) enviar o resultado ao site; UN5_NETPLAY_SESSION
        # nao e usado aqui para nao ligar presenca/allow do netplay casual.
        session = getattr(self.backend, 'session', '') or ''
        self._spawn(args, label, allow_missing_symbols=(role == "guest"),
                    session_env={'UN5_SCOREBOARD_SESSION': session} if session else None, cfg=cfg)

    def solo(self):
        if not self._pick_game():
            return
        args = self._args("solo")
        if args:
            self._spawn(args, tr("run.solo", c=self.v["control"].get()))

    def stop(self):
        if not self.backend.running:
            return
        try:
            self.backend.request_stop()
        except OSError as exc:
            self._log(tr("log.stopfile", exc=exc), "error")
        self._log(tr("log.stopping"), "info")
        self.stop_btn.configure(state="disabled")
        self.after(15000 if self.backend.session_role == 'hill' else 4500,
                   lambda proc=self.backend.proc: self._force(proc))

    def _force(self, expected_proc):
        if self.backend.proc is not expected_proc:
            return
        if self.backend.force_stop():
            self._log(tr("log.forced"), "warn")
            self.after(600, self.release_game)

    def release_game(self):
        if self.backend.running:
            return
        self._oneshot(["stop"], tr("run.releasing"), "release")

    def _oneshot(self, args, label, token):
        try:
            self.backend.oneshot(self.cfg(), args, token)
        except ValueError as exc:
            return messagebox.showerror(tr("dlg.cannot_run"), str(exc))
        self._log(f"\n▶ {label}", "info")
        self._set_buttons(True)
        self.stop_btn.configure(state="disabled")

    def test_pine(self):
        if self.backend.running:
            return
        try:
            self.backend.test_pine(self.cfg())
        except ValueError as exc:
            return messagebox.showerror(tr("dlg.pine_missing"), str(exc))
        self.pine_btn.configure(state="disabled")
        self._log("\n▶ " + tr("run.testing_pine"), "info")

    # ================================================================ eventos do backend
    def _drain(self):
        try:
            while True:
                ev = self.backend.q.get_nowait()
                kind = ev[0]
                if kind == "line":
                    self._on_line(ev[1])
                elif kind == 'koth_events':
                    if ev[1] is self.koth_panel:
                        self.koth_panel.update_events(*ev[2:])
                elif kind == 'koth_access':
                    if ev[1] is self.koth_panel:
                        self.koth_panel.update_management_access(*ev[2:])
                elif kind == 'koth_management':
                    if ev[1] is self.koth_panel:
                        self.koth_panel.management_updated(*ev[2:])
                elif kind == 'koth_state':
                    if ev[2] is self.backend.proc and self.backend.session_role == 'hill':
                        state = ev[1]
                        self.koth_live_state = state
                        self.koth_live_event = state['event']
                        self.v['hill_event_id'].set(str(state['event']['id']))
                        self.koth_panel.display(state['event'], state.get('role'), state.get('reason'))
                elif kind in ('koth_enroll', 'koth_watch'):
                    _, url, address, transport, result, error = ev
                    if error:
                        self._koth_pending = False
                        self._set_buttons(False)
                        self.koth_panel.display(self.koth_live_event)
                        self.koth_panel.status.configure(text=error, fg=RED)
                        messagebox.showerror(tr('hill.title'), error)
                    else:
                        if result.get('address_changed'):
                            self._log(tr('koth.address_changed', deducted=result['points_deducted'],
                                         points=result['points']), 'info')
                        self._begin_hill(url, address, result['ticket'], result['event'], observe=kind == 'koth_watch',
                                         transport=transport)
                elif kind == "exit":
                    self._on_exit(ev[1])
                elif kind == "avatar":
                    pass                                  # a lista de salas pega o avatar pronto no proximo refresh
                elif kind == "pine":
                    ok = ev[1]
                    self._log(tr("log.pine_ok" if ok else "log.pine_fail") + (ev[2] or ""),
                              "success" if ok else "error")
                    self.pine_btn.configure(state="normal")
                elif kind == "acct":
                    self._on_acct(ev[1], ev[2], ev[3])
                elif kind == "sync":
                    cont, self._after_sync = self._after_sync, None
                    self._set_buttons(False)
                    if ev[1]:
                        if cont:
                            cont()
                    else:
                        self._koth_pending = False
                        self.koth_panel.display(self.koth_live_event)
                        self._set_status("READY", MUTED)
                        self._log(ev[2], "error")
                        messagebox.showerror(tr("dlg.default_state"), ev[2])
                elif kind == "allow":
                    cont, self._after_allow = self._after_allow, None
                    self._set_buttons(False)
                    if ev[1]:
                        if cont:
                            cont()
                    else:
                        self._set_status("READY", MUTED)
                        self._log(ev[2], "error")
                        messagebox.showerror(tr("dlg.cannot_join"), ev[2])
                elif kind == "publish":
                    self._log(tr("log.published") if ev[1] else tr("log.publish_fail", msg=ev[2]),
                              "success" if ev[1] else "error")
                elif kind == "oneshot":
                    self._log(ev[2] or tr("log.no_output"), "success" if ev[1] == 0 else "error")
                    self._set_buttons(False)
                    if ev[3] == "release":
                        self._set_status("READY", MUTED)
        except queue.Empty:
            pass
        except Exception as exc:                          # noqa: BLE001 - nunca derruba o loop
            self._log(tr("log.ui_err", exc=exc), "error")
        self.after(80, self._drain)

    def _on_line(self, line):
        tag, status = core.classify(line)
        self._log(line, tag)
        if status:
            self._set_status(*status)
        m = re.search(r"state saved: (.+\.p2s)\s*$", line)
        if m:
            self._adopt_saved_state(Path(m.group(1).strip()))

    def _adopt_saved_state(self, saved: Path):
        """O estado que o PREPARE acabou de salvar vira UN5-partida.p2s na pasta de saves do AppData e, se a conta
        logada for a do dono, e publicado no servidor como o save state padrao."""
        dest = core.game_paths(self.game)[0]
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, dest)
        except OSError as exc:
            return self._log(tr("log.copy_fail", dest=dest, exc=exc), "error")
        self._log(tr("log.copied", dest=dest), "success")
        if self.backend.is_admin():
            self._log(tr("log.publishing"), "info")
            self.backend.publish_default(self.game)

    def _on_exit(self, code):
        self._log(tr("log.finished", code=code), "success" if code in (0, None) else "error")
        self.backend.on_exit()
        self._koth_pending = False
        self.koth_live_ticket = ''
        self.koth_observing = False
        self.koth_panel.display(self.koth_live_event)
        self._set_buttons(False)
        if code not in (0, None) and self.status_key != "DESYNC":
            self._set_status("FAILED", RED)
        elif self.status_key not in ("DESYNC", "FROZEN"):
            self._set_status("READY", MUTED)

    def destroy(self):
        core.save_config({**self.raw(), "ignore_desync": False})   # o switch de debug nunca e salvo como ON
        self._close_zerotier_rooms()
        self.backend.shutdown()
        super().destroy()


if __name__ == "__main__":
    Launcher().mainloop()
