#!/usr/bin/env bash
# Lanzador para Fedora Linux. Ejecutar desde una terminal, sin sudo.
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"

echo '========================================'
echo '       UN5 Netplay Launcher (Linux)'
echo '========================================'

fedora_help() {
    echo 'Instala las dependencias de Fedora y vuelve a ejecutar este archivo:' >&2
    echo '  sudo dnf install python3 python3-pip python3-tkinter' >&2
}

if ! command -v python3 >/dev/null 2>&1; then
    fedora_help
    exit 1
fi
if ! python3 -c 'import sys; assert sys.version_info >= (3, 10); import tkinter, venv' >/dev/null 2>&1; then
    echo 'Se necesita Python 3.10 o superior con Tkinter y venv.' >&2
    fedora_help
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    echo 'Creando entorno virtual en .venv...'
    if ! python3 -m venv .venv; then
        fedora_help
        exit 1
    fi
fi
PYTHON="$PWD/.venv/bin/python"
if ! "$PYTHON" -c 'import tkinter; from PIL import Image, ImageDraw, ImageTk' >/dev/null 2>&1; then
    echo 'Instalando Pillow en el entorno virtual...'
    "$PYTHON" -m pip install Pillow
    "$PYTHON" -c 'import tkinter; from PIL import Image, ImageDraw, ImageTk'
fi

echo 'Actualizando certificados TLS (certifi)...'
if ! "$PYTHON" -m pip install --upgrade --quiet --retries 0 --timeout 10 certifi; then
    echo 'AVISO: No se pudo actualizar certifi. Se continúa con los certificados disponibles.' >&2
fi

# UN5_SKIP_UPDATE=1 permite iniciar la versión local sin consultar GitHub.
if [[ "${UN5_SKIP_UPDATE:-0}" != 1 ]]; then
    echo 'Buscando actualizaciones del launcher...'
    "$PYTHON" - <<'PY'
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import tempfile
import urllib.request
import zipfile

root = Path.cwd()
marker = root / '.update_commit'
try:
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    context = ssl.create_default_context()


def download(url, timeout):
    request = urllib.request.Request(url, headers={'User-Agent': 'UN5-Netplay-Updater'})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read()


try:
    commit = json.loads(download('https://api.github.com/repos/zMath3usMSF/UN5-Netplay/commits/main', 10))
    sha = commit['sha']
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('GitHub devolvió un identificador de versión inválido')
    old = marker.read_text().strip() if marker.exists() else ''
    if old == sha:
        print('El launcher ya está actualizado.')
    else:
        print('Actualización disponible. Descargando...')
        # Descargar el mismo commit que se registra, aunque main cambie entretanto.
        archive = download(f'https://github.com/zMath3usMSF/UN5-Netplay/archive/{sha}.zip', 60)
        excluded = {'.git', '.agents', '.codex', '.aws', '.venv', 'venv', '__pycache__',
                    '.vscode', '.idea', 'config.json', 'session.json', 'symbols.json',
                    'un5_launcher.json', '.env', '.update_commit', '1 - Run.sh'}
        with tempfile.TemporaryDirectory(prefix='un5-update-') as tmp:
            staged = []
            with zipfile.ZipFile(io.BytesIO(archive)) as source:
                if f'UN5-Netplay-{sha}/launcher.py' not in source.namelist():
                    raise ValueError('El archivo descargado no contiene launcher.py')
                for entry in source.infolist():
                    parts = PurePosixPath(entry.filename).parts
                    if entry.is_dir() or len(parts) < 2:
                        continue
                    if parts[0] != f'UN5-Netplay-{sha}' or '..' in parts or entry.filename.startswith('/'):
                        raise ValueError('Ruta inválida en la actualización')
                    rel = Path(*parts[1:])
                    if any(p in excluded or re.search(r'\.bak($|[0-9])|\.bak_seguranca$|\.(p2s|key|pem)$', p)
                           for p in rel.parts):
                        continue
                    target = root / rel
                    if any(p.is_symlink() for p in (target, *target.parents)):
                        raise ValueError(f'El destino es un enlace simbólico: {rel}')
                    staged_file = Path(tmp) / rel
                    staged_file.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(entry) as src, staged_file.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                    staged.append((staged_file, target))
            for src, target in staged:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, target)
            temporary_marker = marker.with_suffix('.tmp')
            temporary_marker.write_text(sha)
            os.replace(temporary_marker, marker)
        print('Actualización completada.')
except Exception as error:
    print(f'AVISO: Falló la actualización: {error}')
    print('Se continúa con la versión instalada.')
PY
fi

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo 'Se necesita una sesión gráfica para abrir el launcher.' >&2
    exit 1
fi

echo 'Iniciando launcher...'
exec "$PYTHON" "$PWD/launcher.py" "$@"
