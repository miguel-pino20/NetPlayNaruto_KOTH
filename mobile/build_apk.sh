#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python || ! -x .venv/bin/buildozer ]]; then
    echo 'Prepara mobile/.venv e instala Buildozer; consulta README.md.' >&2
    exit 1
fi
export VIRTUAL_ENV="$PWD/.venv"
export PATH="$PWD/.toolchain/usr/bin:$VIRTUAL_ENV/bin:$PATH"
if [[ -d .toolchain/usr/share/perl5 ]]; then
    export PERL5LIB="$PWD/.toolchain/usr/share/perl5:$PWD/.toolchain/usr/share/perl5/vendor_perl:$PWD/.toolchain/usr/lib64/perl5/vendor_perl${PERL5LIB:+:$PERL5LIB}"
fi
if [[ -z "${JAVA_HOME:-}" && -d /usr/lib/jvm/java-21-temurin-jdk ]]; then
    export JAVA_HOME=/usr/lib/jvm/java-21-temurin-jdk
fi
.venv/bin/python prepare.py
.venv/bin/buildozer android debug
.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path
import shutil
import sys
root = Path.cwd().parent
sys.path.insert(0, str(root))
from release_info import VERSION, ASSET_NAMES
matches = [p for p in Path('bin').glob('narutonetplay-*-arm64-v8a-debug.apk')
           if p.name.lower() == f'narutonetplay-{VERSION}-arm64-v8a-debug.apk'.lower()]
if len(matches) != 1:
    raise SystemExit('No se encontró el APK de la versión compartida: ' + VERSION)
destination = root / 'dist' / ASSET_NAMES['android']
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(matches[0], destination)
Path(str(destination) + '.sha256').write_text(
    hashlib.sha256(destination.read_bytes()).hexdigest() + '  ' + destination.name + '\n')
print('Listo:', destination)
PY
