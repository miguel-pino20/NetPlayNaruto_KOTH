"""GitHub release updates for the portable EXE and AppImage, before netplay starts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import release_info

MAX_ASSET_SIZE = 256 * 1024 * 1024
MAX_METADATA_SIZE = 2 * 1024 * 1024
STAGE_PREFIX = ".un5-update-"
LOG = logging.getLogger("un5.updater")


class UpdateError(Exception):
    pass


class Cancelled(UpdateError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    asset_url: str
    checksum_url: str
    size: int
    asset_name: str


def version_key(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-?(alpha|beta|rc|a|b)(?:[.-]?(\d+))?)?",
                         value.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"Versión inválida: {value}")
    major, minor, patch, phase, sequence = match.groups()
    rank = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2, None: 3}
    return int(major), int(minor), int(patch), rank[phase.lower() if phase else None], int(sequence or 0)


def current_binary():
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    if sys.platform.startswith("linux") and os.environ.get("APPIMAGE"):
        path = Path(os.environ["APPIMAGE"]).resolve()
        if path.is_file():
            return path
    return None  # Running source or an extracted AppDir never replaces source files.


def asset_url_allowed(url, repository):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc.lower() == "github.com"
            and parsed.path.startswith(f"/{repository}/releases/download/")
            and not parsed.query and not parsed.fragment)


def select_release(releases, current_version, platform, repository, include_prereleases=True):
    current = version_key(current_version)
    expected = release_info.ASSET_NAMES[platform]
    candidates = []
    for entry in releases:
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        if entry.get("prerelease") and not include_prereleases:
            continue
        try:
            version = entry["tag_name"]
            key = version_key(version)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue  # Old unnumbered tags, including "Alpha", have no ordering.
        if key <= current:
            continue
        entries = entry.get("assets")
        if not isinstance(entries, list):
            continue
        assets = {a.get("name"): a for a in entries if isinstance(a, dict) and isinstance(a.get("name"), str)}
        binary, checksum = assets.get(expected), assets.get(expected + ".sha256")
        if not binary or not checksum:
            continue
        url, checksum_url = binary.get("browser_download_url", ""), checksum.get("browser_download_url", "")
        size = binary.get("size", 0)
        if (not isinstance(size, int) or not 0 < size <= MAX_ASSET_SIZE
                or not asset_url_allowed(url, repository) or not asset_url_allowed(checksum_url, repository)):
            continue
        # Both assets must belong to the same tag, even if remote metadata is malformed.
        if url.rsplit("/", 1)[0] != checksum_url.rsplit("/", 1)[0]:
            continue
        candidates.append((key, Release(version, url, checksum_url, size, expected)))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


class GithubRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        parsed = urlsplit(new_url)
        if parsed.scheme != "https" or parsed.netloc.lower() not in {
            "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
        }:
            raise UpdateError("La descarga intentó salir de los servidores HTTPS de GitHub.")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def _response(url, timeout):
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    request = Request(url, headers={"User-Agent": f"UN5-Netplay/{release_info.VERSION}",
                                    "Accept": "application/vnd.github+json" if "api.github.com/" in url else "*/*"})
    opener = build_opener(HTTPSHandler(context=context), GithubRedirects())
    return opener.open(request, timeout=timeout)


def find_update(platform):
    repository = release_info.REPOSITORY
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise UpdateError("El repositorio de actualizaciones no está configurado.")
    url = f"https://api.github.com/repos/{repository}/releases?per_page=100"
    with _response(url, 6) as response:
        data = response.read(MAX_METADATA_SIZE + 1)
    if len(data) > MAX_METADATA_SIZE:
        raise UpdateError("La respuesta de GitHub es demasiado grande.")
    entries = json.loads(data)
    if not isinstance(entries, list):
        raise UpdateError("GitHub devolvió una respuesta de releases inválida.")
    return select_release(entries, release_info.VERSION, platform, repository, release_info.INCLUDE_PRERELEASES)


def parse_checksum(data, filename):
    try:
        line, = data.decode("utf-8-sig").strip().splitlines()
    except (UnicodeError, ValueError):
        raise UpdateError("El archivo SHA256 es inválido.") from None
    match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?(.+)", line)
    if not match or match[2] != filename:
        raise UpdateError("El SHA256 no corresponde al archivo de esta plataforma.")
    return match[1].lower()


def verify_payload(path, digest, platform):
    calculated = hashlib.sha256()
    with path.open("rb") as source:
        header = source.read(16)
        calculated.update(header)
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            calculated.update(chunk)
    if calculated.hexdigest() != digest:
        raise UpdateError("La descarga no coincide con su SHA256; se conserva la versión instalada.")
    if platform == "linux" and not (header.startswith(b"\x7fELF") and header[8:11] == b"AI\x02"):
        raise UpdateError("La descarga no es un AppImage válido.")
    if platform == "windows" and not header.startswith(b"MZ"):
        raise UpdateError("La descarga no es un ejecutable de Windows válido.")


def download_release(release, stage, platform, progress, cancelled):
    with _response(release.checksum_url, 10) as response:
        checksum_data = response.read(4097)
    if len(checksum_data) > 4096:
        raise UpdateError("El archivo SHA256 es demasiado grande.")
    digest = parse_checksum(checksum_data, release.asset_name)
    payload = stage / ("payload.exe" if platform == "windows" else "payload.AppImage")
    count = 0
    with _response(release.asset_url, 15) as response, payload.open("xb") as target:
        while True:
            if cancelled.is_set():
                raise Cancelled()
            chunk = response.read(128 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > release.size or count > MAX_ASSET_SIZE:
                raise UpdateError("El tamaño de la descarga no corresponde a la release.")
            target.write(chunk)
            progress(count, release.size)
        target.flush()
        os.fsync(target.fileno())
    if cancelled.is_set():
        raise Cancelled()
    if count != release.size:
        raise UpdateError("La descarga quedó incompleta; se conserva la versión instalada.")
    verify_payload(payload, digest, platform)
    return payload, digest


def restart_environment(stage):
    # Remove paths into an old AppImage mount / PyInstaller extraction directory.
    remove = {"APPIMAGE", "APPDIR", "ARGV0", "OWD", "APPIMAGE_COMMAND", "TCL_LIBRARY", "TK_LIBRARY",
              "TKPATH", "SSL_CERT_FILE", "PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "LD_PRELOAD"}
    env = {key: value for key, value in os.environ.items() if key not in remove and not key.startswith("_PYI_")}
    env.update(PYINSTALLER_RESET_ENVIRONMENT="1", APPIMAGELAUNCHER_DISABLE="1",
               UN5_SKIP_RELEASE_CHECK_ONCE="1", UN5_UPDATE_STAGE=str(stage))
    return env


def start_binary(target, stage):
    return subprocess.Popen([str(target)], cwd=str(target.parent), env=restart_environment(stage),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def write_request(stage, target, digest):
    path = stage / "request.json"
    data = {"target": str(target), "sha256": digest, "parent_pid": os.getpid()}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def replace_and_restart(target, payload, stage, retry_seconds=0):
    """Atomic payload install with rollback if replacing or starting fails."""
    backup = stage / "previous"
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            os.replace(target, backup)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    try:
        os.replace(payload, target)
        process = start_binary(target, stage)
    except Exception:
        os.replace(backup, target)
        raise
    return process


def schedule_install(target, payload, digest, stage, platform):
    write_request(stage, target, digest)
    if platform == "windows":
        # A separate copy keeps running after the old EXE (and its bootloader) exit.
        helper = stage / "update-helper.exe"
        shutil.copy2(target, helper)
        return subprocess.Popen([str(helper), "--apply-update", str(stage / "request.json")],
                                cwd=str(stage), env=restart_environment(stage), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    payload.chmod(stat.S_IMODE(target.stat().st_mode) & 0o777 | stat.S_IXUSR)
    return replace_and_restart(target, payload, stage)


def _wait_windows_parent(pid):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 60000) != 0:
                raise UpdateError("La versión anterior todavía está abierta.")
        finally:
            kernel.CloseHandle(handle)


def _configure_log():
    import appdata
    if not LOG.handlers:
        try:
            handler = logging.FileHandler(appdata.DATA_DIR / "updater.log", encoding="utf-8")
        except OSError:
            LOG.addHandler(logging.NullHandler())
            return
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)


def apply_windows_update(request_path):
    """Internal helper mode; never opens the launcher or checks GitHub."""
    _configure_log()
    target = None
    stage = request_path.resolve().parent
    try:
        if (request_path.name != "request.json" or not stage.name.startswith(STAGE_PREFIX)
                or stage != Path(sys.executable).resolve().parent):
            raise UpdateError("Solicitud de actualización inválida.")
        if request_path.stat().st_size > 16384:
            raise UpdateError("Solicitud de actualización demasiado grande.")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        candidate = Path(request["target"]).resolve()
        if stage.parent != candidate.parent or candidate.suffix.lower() != ".exe" or candidate.parent == stage:
            raise UpdateError("Destino de actualización inválido.")
        target = candidate
        payload = stage / "payload.exe"
        verify_payload(payload, request["sha256"], "windows")
        _wait_windows_parent(int(request["parent_pid"]))
        replace_and_restart(target, payload, stage, retry_seconds=30)
        LOG.info("Actualización de Windows instalada: %s", target)
        return 0
    except Exception:
        LOG.exception("Falló la instalación de la actualización de Windows")
        if target and target.is_file():
            try:
                start_binary(target, stage)
            except Exception:
                LOG.exception("No se pudo reiniciar la versión instalada")
        return 1


def confirm_startup():
    """Delete the old binary only after the new launcher's window was created."""
    value = os.environ.pop("UN5_UPDATE_STAGE", "")
    target = current_binary()
    if not value or not target:
        return
    stage = Path(value)
    try:
        if stage.is_symlink() or not stage.name.startswith(STAGE_PREFIX) or stage.resolve().parent != target.parent:
            return
        request = json.loads((stage / "request.json").read_text(encoding="utf-8"))
        if Path(request["target"]).resolve() != target:
            return
    except (OSError, ValueError, KeyError):
        return

    def cleanup():
        for _ in range(20):
            try:
                shutil.rmtree(stage)
                return
            except FileNotFoundError:
                return
            except OSError:  # The Windows helper may still be exiting.
                time.sleep(0.5)
    threading.Thread(target=cleanup, daemon=True).start()


def check_for_updates_on_startup():
    """Return True when a new process was scheduled and this one must exit."""
    if os.environ.pop("UN5_SKIP_RELEASE_CHECK_ONCE", "") == "1":
        return False
    target = current_binary()
    if target is None:
        return False
    _configure_log()
    import tkinter as tk
    from tkinter import ttk
    try:
        root = tk.Tk(className="Un5netplay")
    except tk.TclError:
        LOG.exception("No se pudo abrir la ventana de actualización")
        return False
    root.title("UN5 Netplay · Actualización")
    root.geometry("490x180")
    root.resizable(False, False)
    icon = Path(__file__).with_name("un5-netplay.png")
    if icon.is_file():
        root._app_icon = tk.PhotoImage(file=str(icon))
        root.iconphoto(True, root._app_icon)
    label = ttk.Label(root, text="Buscando actualizaciones…", wraplength=445, anchor="center")
    label.pack(fill="x", padx=20, pady=(22, 12))
    bar = ttk.Progressbar(root, mode="indeterminate")
    bar.pack(fill="x", padx=25)
    bar.start()
    status = ttk.Label(root, text=f"Versión instalada: {release_info.VERSION}")
    status.pack(pady=8)
    messages = queue.Queue()
    cancelled = threading.Event()
    lock = threading.Lock()
    state = {"installing": False, "restart": False}

    def cancel():
        with lock:
            if state["installing"]:
                return
            cancelled.set()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", cancel)

    def work():
        stage = None
        retain = False
        try:
            platform = "windows" if sys.platform == "win32" else "linux"
            release = find_update(platform)
            if not release or cancelled.is_set():
                messages.put(("done", False))
                return
            messages.put(("found", release.version))
            stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=target.parent))
            payload, digest = download_release(
                release, stage, platform, lambda done, total: messages.put(("progress", (done, total))), cancelled)
            with lock:
                if cancelled.is_set():
                    return
                state["installing"] = True
            messages.put(("install", None))
            schedule_install(target, payload, digest, stage, platform)
            retain = True  # New launcher cleans up once its own window is ready.
            messages.put(("done", True))
        except Cancelled:
            pass
        except Exception:
            LOG.exception("No se pudo actualizar; se abrirá la versión instalada")
            messages.put(("error", None))
        finally:
            if stage is not None and not retain:
                shutil.rmtree(stage, ignore_errors=True)

    def poll():
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == "found":
                    bar.stop()
                    bar.configure(mode="determinate", maximum=100, value=0)
                    label.configure(text=f"Nueva actualización {value}. Descargando, espera…")
                elif kind == "progress":
                    done, total = value
                    bar.configure(value=done * 100 / total)
                    status.configure(text=f"{done / 1024**2:.1f} / {total / 1024**2:.1f} MB")
                elif kind == "install":
                    label.configure(text="Descarga verificada. Reiniciando el launcher…")
                elif kind == "error":
                    bar.stop()
                    label.configure(text="No se pudo comprobar o descargar la actualización.\nSe abrirá la versión instalada.")
                    root.after(1800, root.destroy)
                    return
                elif kind == "done":
                    state["restart"] = value
                    root.destroy()
                    return
        except queue.Empty:
            root.after(60, poll)
    threading.Thread(target=work, daemon=True).start()
    root.after(60, poll)
    root.mainloop()
    return state["restart"]
