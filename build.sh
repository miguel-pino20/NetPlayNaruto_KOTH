#!/usr/bin/env bash
# Compila los paquetes de Linux y Windows desde Linux, sin abrir el launcher.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
cd -- "$project_root"

usage() {
    cat <<'HELP'
Uso: ./build.sh [all|linux|windows]

Sin argumentos compila Linux y Windows.
  ./build.sh linux     Solo AppImage
  ./build.sh windows   Solo EXE mediante el Wine preparado del proyecto

Configura VERSION en release_info.py antes de compilar.
Los paquetes y sus SHA256 quedan en dist/.
Windows requiere pip de Linux; descarga los wheels que falten en la caché.
HELP
}

if [[ $# -gt 1 ]]; then
    usage >&2
    exit 2
fi
build_target="${1:-all}"
case "$build_target" in
    -h|--help) usage; exit 0 ;;
    all|linux|windows) ;;
    *) usage >&2; exit 2 ;;
esac

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    printf 'Este script necesita Linux x86_64.\n' >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf 'No se encontró python3. Instálalo antes de compilar.\n' >&2
    exit 1
fi

# Comprobar Windows antes de empezar para evitar una compilación parcial por
# falta de Wine. Nunca se utiliza ni modifica el prefijo ~/.wine del usuario.
windows_prefix="$project_root/.windows-cache/wine"
windows_python="$windows_prefix/drive_c/Python313/python.exe"
windows_wheels="$project_root/.windows-cache/wheels"
if [[ "$build_target" == all || "$build_target" == windows ]]; then
    if ! command -v wine >/dev/null 2>&1; then
        printf 'No se encontró Wine. Instálalo para compilar Windows.\n' >&2
        exit 1
    fi
    if [[ ! -f "$windows_python" || ! -f "$windows_prefix/drive_c/Python313/tcl/tcl8.6/init.tcl" ]]; then
        printf 'Falta Python de Windows con Tcl/Tk en:\n  %s\n' "$windows_prefix/drive_c/Python313" >&2
        printf 'Consulta windows/README.md para preparar ese prefijo Wine.\n' >&2
        exit 1
    fi
fi

PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Se necesita Python 3.10 o superior.')
import release_info
from updater import version_key
version_key(release_info.VERSION)
print(f'Compilando UN5 Netplay {release_info.VERSION}', flush=True)
print(f'Releases: {release_info.REPOSITORY}', flush=True)
PY

# No basta con encontrar cualquier wheel: la caché puede pertenecer a una
# versión anterior de requirements-build.txt. Resolver primero sin red permite
# seguir compilando offline cuando ya están todas las dependencias.
if [[ "$build_target" == all || "$build_target" == windows ]]; then
    if ! python3 -m pip --version >/dev/null 2>&1; then
        printf 'Falta pip de Python 3 en Linux para preparar los wheels de Windows.\n' >&2
        exit 1
    fi
    mkdir -p "$windows_wheels"
    # pip evalúa sys_platform en Linux incluso con --platform win_amd64.
    # Incluir las dependencias condicionales de PyInstaller para Windows.
    wheel_args=(--only-binary=:all: --platform win_amd64 --python-version 3.13
                --implementation cp --abi cp313 --dest "$windows_wheels"
                --find-links "$windows_wheels" -r "$project_root/windows/requirements-build.txt"
                'pefile>=2022.5.30' 'pywin32-ctypes>=0.2.1')
    printf '\nComprobando dependencias de Windows…\n'
    if ! python3 -m pip --no-cache-dir download --no-index "${wheel_args[@]}"; then
        printf '\nDescargando dependencias que faltan en la caché de Windows…\n'
        python3 -m pip --no-cache-dir download "${wheel_args[@]}"
    fi
fi

if [[ "$build_target" == all || "$build_target" == linux ]]; then
    printf '\nCompilando Linux AppImage…\n'
    python3 appimage/build_appimage.py
fi

if [[ "$build_target" == all || "$build_target" == windows ]]; then
    printf '\nCompilando Windows EXE mediante Wine…\n'
    env WINEPREFIX="$windows_prefix" \
        WINEDEBUG=-all \
        WINEDLLOVERRIDES='mscoree,mshtml=' \
        TCL_LIBRARY='C:/Python313/tcl/tcl8.6' \
        TK_LIBRARY='C:/Python313/tcl/tk8.6' \
        wine 'C:\Python313\python.exe' windows/build_windows.py --wheel-dir "$windows_wheels"
fi

PYTHONDONTWRITEBYTECODE=1 python3 - "$build_target" <<'PY'
import hashlib
from pathlib import Path
import sys
from release_info import ASSET_NAMES

platforms = ('linux', 'windows') if sys.argv[1] == 'all' else (sys.argv[1],)
for platform in platforms:
    path = Path('dist') / ASSET_NAMES[platform]
    checksum = Path(str(path) + '.sha256')
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum.read_text().split()[0]:
        raise SystemExit(f'Error al comprobar el SHA256: {path}')
    print(f'Listo: {path} y {checksum.name}')
print(f'\nArchivos para la release: {Path("dist").resolve()}')
PY
