"""Start the bundled launcher and the user's PCSX2 Flatpak."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback

PROJECT = Path(__file__).resolve().parent
FLATPAK_ID = "net.pcsx2.PCSX2"


def show_error(message):
    print(message, file=sys.stderr, flush=True)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("UN5 Netplay", message, parent=root)
        root.destroy()
    except Exception:
        pass  # A terminal still displays the error when no graphical session exists.


def check_flatpak():
    if not shutil.which("flatpak"):
        raise RuntimeError("No se encontró Flatpak. Instala Flatpak y PCSX2 para abrir UN5 Netplay.")
    result = subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(
            "PCSX2 no está instalado mediante Flatpak. Instálalo y vuelve a abrir este AppImage:\n\n"
            "flatpak install flathub net.pcsx2.PCSX2"
        )


def self_test():
    import tkinter
    from PIL import Image, ImageDraw, ImageTk
    import certifi
    import launcher
    import ssl
    assert Path(tkinter.Tcl().eval("info library")).is_dir()
    ssl.create_default_context(cafile=certifi.where())
    result = subprocess.run([sys.executable, str(PROJECT / "netplay.py"), "--help"],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    print(f"OK: Python {sys.version.split()[0]}, Tcl/Tk, Pillow, TLS, launcher y proceso netplay.")
    return 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    try:
        check_flatpak()
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise RuntimeError("Se necesita una sesión gráfica para abrir UN5 Netplay y PCSX2.")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        show_error(str(error))
        return 1

    logs = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "un5-netplay"
    logs.mkdir(parents=True, exist_ok=True)
    # STOP must write outside the read-only AppImage mount. Each launch has its own directory.
    with tempfile.TemporaryDirectory(prefix="un5-netplay-") as temporary, \
            (logs / "pcsx2.log").open("a", encoding="utf-8") as pcsx2_log, \
            (logs / "launcher.log").open("a", encoding="utf-8", buffering=1) as launcher_log:
        os.environ["TEMP"] = temporary
        original_stdout, original_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = sys.stderr = launcher_log
            pcsx2 = subprocess.Popen(["bash", str(PROJECT / "2 - PCSX2 Flatpak.sh")],
                                     stdout=pcsx2_log, stderr=subprocess.STDOUT)
            try:
                code = pcsx2.wait(timeout=0.8)
            except subprocess.TimeoutExpired:
                code = None
            if code not in (0, None):
                raise RuntimeError(f"No se pudo abrir PCSX2. Revisa el registro:\n{logs / 'pcsx2.log'}")
            from launcher import Launcher
            Launcher().mainloop()
            return 0
        except Exception as error:
            traceback.print_exc()
            show_error(f"{error}\n\nRegistro: {logs / 'launcher.log'}")
            return 1
        finally:
            # PCSX2 remains open when the launcher closes, as with the original scripts.
            sys.stdout, sys.stderr = original_stdout, original_stderr


if __name__ == "__main__":
    raise SystemExit(main())
