"""Run a Git checkout on Windows using its own Windows virtual environment.

No source updates, global package installs, executable builds or PCSX2 launch.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENT = ROOT / '.venv-win'
REQUIREMENTS = ROOT / 'windows' / 'requirements-run.txt'


def usable_environment(python, environment):
    code = ('import sys, tkinter, ssl, venv; '
            'assert sys.version_info >= (3, 10) and sys.maxsize > 2**32; '
            'assert sys.prefix != sys.base_prefix')
    try:
        return subprocess.run([str(python), '-I', '-c', code], env=environment,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def dependencies_ready(python, environment):
    pins = []
    for line in REQUIREMENTS.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            name, version = line.split('==')
            pins.append((name.strip(), version.strip()))
    code = ('import sys, json, ssl, tkinter, certifi; '
            'from PIL import Image, ImageDraw, ImageTk; '
            'from importlib.metadata import version; '
            'assert all(version(name) == expected for name, expected in json.loads(sys.argv[1])); '
            'ssl.create_default_context(cafile=certifi.where())')
    return subprocess.run([str(python), '-I', '-c', code, json.dumps(pins)], env=environment,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main():
    if sys.platform != 'win32' or sys.version_info < (3, 10) or sys.maxsize <= 2**32:
        raise RuntimeError('Se necesita Python de Windows de 64 bits, version 3.10 o posterior.')
    environment = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH'):
        environment.pop(name, None)
    environment.update(PYTHONNOUSERSITE='1', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                       PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1', PIP_REQUIRE_VIRTUALENV='1')
    python = ENVIRONMENT / 'Scripts' / 'python.exe'
    if not usable_environment(python, environment):
        if ENVIRONMENT.exists():
            backup = ROOT / ('.venv-win-backup-' + uuid4().hex)
            ENVIRONMENT.rename(backup)
            print('El entorno anterior no se puede reutilizar; se conservo como ' + backup.name, flush=True)
        print('Creando el entorno de Python de Windows...', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(ENVIRONMENT)], env=environment, check=True)
        if not usable_environment(python, environment):
            raise RuntimeError('El entorno no dispone de Tcl/Tk. Reinstala Python con la opcion Tcl/Tk e IDLE.')
    if not dependencies_ready(python, environment):
        print('Preparando Pillow y certificados TLS en .venv-win...', flush=True)
        pip = subprocess.run([str(python), '-m', 'pip', '--version'], env=environment,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if pip.returncode:
            subprocess.run([str(python), '-m', 'ensurepip'], env=environment, check=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '--timeout', '20', '--retries', '1',
                        '-r', str(REQUIREMENTS)], env=environment, check=True)
        if not dependencies_ready(python, environment):
            raise RuntimeError('No se pudieron preparar las dependencias del launcher.')
    print('Abriendo el launcher desde el proyecto local...', flush=True)
    return subprocess.run([str(python), str(ROOT / 'windows' / 'windows_start.py'), *sys.argv[1:]],
                          cwd=ROOT, env=environment).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('No se pudo iniciar UN5 Netplay: ' + str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
