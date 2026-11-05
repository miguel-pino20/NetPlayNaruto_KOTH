"""Windows executable entry point, including the launcher's Python worker commands."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import traceback

WORKER_SCRIPTS = {"netplay.py", "pine.py"}


def project_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def worker_script(arguments):
    """Accept the Python-style command lines already used by Backend and KOTH."""
    arguments = list(arguments)
    if arguments[:1] == ["-u"]:
        arguments.pop(0)
    if not arguments or Path(arguments[0]).name not in WORKER_SCRIPTS:
        raise ValueError("Comando de netplay desconocido.")
    expected = project_dir() / Path(arguments[0]).name
    if Path(arguments[0]).resolve() != expected.resolve():
        raise ValueError("Solo se pueden ejecutar los módulos incluidos en el launcher.")
    return expected, arguments[1:]


def run_worker(arguments):
    script, args = worker_script(arguments)
    sys.argv = [str(script), *args]
    # PyInstaller is built in console mode with its owned console hidden, so
    # CREATE_NO_WINDOW workers still retain the stdout pipe used by Backend.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(line_buffering=True, write_through=True)
    runpy.run_path(str(script), run_name="__main__")
    return 0


def self_test():
    import tkinter
    from PIL import Image, ImageDraw, ImageTk
    import certifi
    import ssl
    import launcher
    assert Path(tkinter.Tcl().eval("info library")).is_dir()
    ssl.create_default_context(cafile=certifi.where())
    # Exercise the exact frozen-executable dispatch that HOST/GUEST/KOTH use.
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve()))
    command += ["-u", str(project_dir() / "netplay.py"), "--help"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or "usage:" not in result.stdout.lower():
        raise RuntimeError(f"Falló el proceso netplay ({result.returncode}): {result.stderr}")
    print(f"OK: Windows launcher, Python {sys.version.split()[0]}, Tcl/Tk, Pillow, TLS y netplay.", flush=True)
    return 0


def run_gui(smoke_test=False):
    import appdata
    log_path = appdata.DATA_DIR / "launcher.log"
    with log_path.open("a", encoding="utf-8", buffering=1) as log, \
            contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            from launcher import Launcher
            app = Launcher()
            if smoke_test:
                app.after(800, app.destroy)
            app.mainloop()
            return 0
        except Exception as error:
            traceback.print_exc()
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("UN5 Netplay", f"{error}\n\nRegistro: {log_path}", parent=root)
            root.destroy()
            return 1


def main(arguments=None):
    args = list(sys.argv[1:] if arguments is None else arguments)
    sys.path.insert(0, str(project_dir()))
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ.setdefault("TEMP", tempfile.gettempdir())
    if args == ["--self-test"]:
        return self_test()
    if args == ["--smoke-test-gui"]:
        return run_gui(smoke_test=True)
    if args:
        return run_worker(args)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
