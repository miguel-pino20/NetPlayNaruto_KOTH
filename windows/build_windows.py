#!/usr/bin/env python3
"""Build the single Windows x64 executable using native Windows Python (or Wine)."""
import argparse
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent.parent
MODULES = ("appdata core_link discord_auth hill i18n koth_client launcher launcher_account "
           "launcher_avatar launcher_core launcher_koth launcher_theme lockstep netlink netplay "
           "node pine release_info rooms simgame spectator statesync updater wire zerotier_networks "
           "build_don disc_image don_adapter don_core don_profiles don_setup don_online don_routing launcher_don mips_link multiplayer_client").split()


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, help="Optional offline directory of build dependency wheels")
    args = parser.parse_args()
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("Usa Python de Windows de 64 bits, en Windows o mediante Wine.")
    if sys.version_info < (3, 11):
        raise RuntimeError("Se necesita Python 3.11 o superior para Pillow 13.")
    build = ROOT / "build/windows"
    build.mkdir(parents=True, exist_ok=True)
    env_dir = build / "venv"
    if not (env_dir / "Scripts/python.exe").exists():
        venv.EnvBuilder(with_pip=True).create(env_dir)
    python = env_dir / "Scripts/python.exe"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(PYTHONNOUSERSITE="1", PIP_NO_CACHE_DIR="1", PYTHONDONTWRITEBYTECODE="1")
    pip_args = ["--no-index", "--find-links", args.wheel_dir.resolve()] if args.wheel_dir else []
    run(python, "-m", "pip", "install", *pip_args, "-r", ROOT / "windows/requirements-build.txt", env=env)
    run(python, "-c", "import tkinter; print('Tcl/Tk:', tkinter.Tcl().eval('info library'))", env=env)
    icon = build / "un5-netplay.ico"
    run(python, "-c", "from PIL import Image; import sys; Image.open(sys.argv[1]).convert('RGBA').save(sys.argv[2], sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])",
        ROOT / "appimage/un5-netplay.png", icon, env=env)
    # Every added source file is deliberate: no .bat/.sh, PCSX2, games, user data or secrets.
    data_files = [ROOT / f"{module}.py" for module in MODULES]
    data_files += [ROOT / "symbols_un6.json", ROOT / "appimage/un5-netplay.png", icon]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        data_files.append(python_license)
    command = [python, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
               "--hide-console", "hide-early", "--name", "UN5-Netplay-Windows-x64", "--icon", icon,
               "--distpath", ROOT / "dist", "--workpath", build / "pyinstaller", "--specpath", build,
               "--paths", ROOT, "--collect-data", "certifi", "--copy-metadata", "certifi",
               "--copy-metadata", "Pillow"]
    for path in data_files:
        command += ["--add-data", f"{path}{os.pathsep}."]
    command += ["--add-data", f"{ROOT / 'windows/README.md'}{os.pathsep}."]
    command += ["--add-data", f"{ROOT / 'UPDATES.md'}{os.pathsep}."]
    for module in MODULES:
        command += ["--hidden-import", module]
    command += ["--hidden-import", "PIL.ImageTk", ROOT / "windows/windows_start.py"]
    run(*command, env=env)
    output = ROOT / "dist/UN5-Netplay-Windows-x64.exe"
    # Separate test profile keeps the build machine's real Discord/config data out of checks.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="un5-windows-check-") as temporary:
        test_env = {**env, "APPDATA": temporary}
        run(output, "--self-test", env=test_env, timeout=45)
    output.with_suffix(".exe.sha256").write_text(
        f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output.name}\n", encoding="utf-8")
    print(f"Listo: {output} ({output.stat().st_size / 1024**2:.1f} MiB)")


if __name__ == "__main__":
    main()
