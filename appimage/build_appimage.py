#!/usr/bin/env python3
"""Build a self-contained x86_64 netplay AppImage; PCSX2 stays in Flatpak."""
from pathlib import Path
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".appimage-cache"
BUILD = ROOT / "build" / "appimage"
DIST = ROOT / "dist"
ASSETS = {
    "python3.12.AppImage": (
        "https://github.com/niess/python-appimage/releases/download/python3.12/"
        "python3.12.15-cp312-cp312-manylinux2014_x86_64.AppImage",
        "a6a9bf619a3e21c5623be144d8ac4e458e1a5b5c133b1cc99b142d6e71b82c76"),
    "appimagetool.AppImage": (
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage",
        "62aebc77c2149e96b593b94da9bbd1881e0984a56399ff6d7a03b7ddd7c9ce68"),
    "runtime-x86_64": (
        "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64",
        "617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46"),
}


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def download(name, url, digest):
    path = CACHE / name
    if not path.exists():
        print(f"Descargando {name}...", flush=True)
        partial = path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=60) as source, partial.open("wb") as target:
            shutil.copyfileobj(source, target)
        partial.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"SHA256 incorrecto: {path}. No se ejecutará el archivo descargado.")
    path.chmod(0o755)
    return path


def extract(image, target):
    target.mkdir(parents=True)
    with (target / "extract.log").open("w") as log:
        run(image, "--appimage-extract", cwd=target, stdout=log)
    return target / "squashfs-root"


def main():
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise RuntimeError("Construye este paquete en Linux x86_64.")
    CACHE.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    assets = {name: download(name, *values) for name, values in ASSETS.items()}
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    source = extract(assets["python3.12.AppImage"], BUILD / "python")
    appdir = BUILD / "UN5-Netplay.AppDir"
    shutil.move(source, appdir)
    tool = extract(assets["appimagetool.AppImage"], BUILD / "tool")
    python = appdir / "usr/bin/python3.12"
    env = {k: v for k, v in os.environ.items()
           if k not in ("APPIMAGE", "APPDIR", "PYTHONHOME", "PYTHONPATH")}
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PIP_NO_CACHE_DIR="1")
    # Downloads only at build time. The distributed AppImage never invokes pip.
    requirements = ROOT / "appimage/requirements.txt"
    cached_pillow = CACHE / "pillow-12.0.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
    if not cached_pillow.exists():
        run(python, "-m", "pip", "download", "--only-binary=:all:", "--no-deps", "--require-hashes",
            "--dest", CACHE, "-r", requirements, env=env)
    run(python, "-m", "pip", "install", "--no-index", "--find-links", CACHE, "--require-hashes",
        "--no-deps", "-r", requirements, env=env)
    project = appdir / "usr/share/un5-netplay"
    project.mkdir(parents=True)
    # Include source files, never a virtualenv, account/session data, BIOS or games.
    modules = ("appdata core_link discord_auth hill i18n koth_client launcher launcher_account "
               "launcher_avatar launcher_core launcher_koth launcher_theme lockstep netlink netplay "
               "node pine release_info rooms simgame spectator statesync updater wire zerotier_networks "
               "build_don disc_image don_adapter don_core don_profiles don_setup don_online don_routing launcher_don mips_link multiplayer_client").split()
    for module in modules:
        shutil.copy2(ROOT / f"{module}.py", project / f"{module}.py")
    for name in ("2 - PCSX2 Flatpak.sh", "symbols_un6.json", "README.md", "UPDATES.md"):
        shutil.copy2(ROOT / name, project / name)
    shutil.copy2(ROOT / "appimage/appimage_start.py", project / "appimage_start.py")
    (project / "appimage").mkdir()
    shutil.copy2(ROOT / "appimage/README.md", project / "appimage/README.md")
    # Replace only the root entry points; preserve the upstream Python wrapper.
    for path in (*appdir.glob("*.desktop"), appdir / "AppRun", appdir / ".DirIcon", appdir / "python.png"):
        path.unlink(missing_ok=True)
    for name in ("AppRun", "un5-netplay.desktop"):
        shutil.copy2(ROOT / "appimage" / name, appdir / name)
    # Desktop integrators copy themed icons from this directory, not just .DirIcon.
    # Pillow saves conventional 8-bit RGBA PNGs for compatibility with icon loaders.
    run(python, "-c", "\n".join([
        "from pathlib import Path",
        "from PIL import Image",
        "import sys",
        "source = Image.open(sys.argv[1]).convert('RGBA')",
        "root = Path(sys.argv[2])",
        "for size in (16, 24, 32, 48, 64, 128, 256):",
        "    path = root / f'usr/share/icons/hicolor/{size}x{size}/apps/un5-netplay.png'",
        "    path.parent.mkdir(parents=True, exist_ok=True)",
        "    source.resize((size, size), Image.Resampling.LANCZOS).save(path)",
    ]), ROOT / "appimage/un5-netplay.png", appdir, env=env)
    icon = appdir / "usr/share/icons/hicolor/256x256/apps/un5-netplay.png"
    shutil.copy2(icon, appdir / "un5-netplay.png")
    shutil.copy2(icon, project / "un5-netplay.png")
    applications = appdir / "usr/share/applications"
    applications.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "appimage/un5-netplay.desktop", applications / "un5-netplay.desktop")
    (appdir / "AppRun").chmod(0o755)
    (appdir / ".DirIcon").symlink_to("un5-netplay.png")
    (project / "BUILD-SOURCES.txt").write_text("\n".join(
        f"{name}\n{url}\nSHA256 {digest}\n" for name, (url, digest) in ASSETS.items()) +
        "\nPCSX2 is NOT bundled. Uses the installed net.pcsx2.PCSX2 Flatpak.\n", encoding="utf-8")
    # Downloaded AppDirs may have owner-only directory modes.
    for folder, dirs, files in os.walk(appdir):
        Path(folder).chmod(0o755)
        for name in files:
            path = Path(folder) / name
            if not path.is_symlink():
                path.chmod(0o755 if os.access(path, os.X_OK) else 0o644)
    run(appdir / "AppRun", "--self-test", env=env)
    output = DIST / "UN5-Netplay-x86_64.AppImage"
    run(tool / "AppRun", "--no-appstream", "--runtime-file", assets["runtime-x86_64"],
        "--mksquashfs-opt", "-processors", "--mksquashfs-opt", "2", appdir, output,
        env={**env, "ARCH": "x86_64"})
    output.chmod(0o755)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".AppImage.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"\nListo: {output} ({output.stat().st_size / 1024**2:.1f} MiB)")


if __name__ == "__main__":
    main()
