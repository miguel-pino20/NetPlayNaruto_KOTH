#!/usr/bin/env bash
# Abre PCSX2 con PINE en un directorio visible fuera de su sandbox.
set -euo pipefail

if ! command -v flatpak >/dev/null 2>&1; then
    echo 'No se encontró Flatpak.' >&2
    exit 1
fi

runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
shared_runtime="$runtime/app/net.pcsx2.PCSX2"
mkdir -p -- "$shared_runtime"

# Mantener la ruta de Wayland al cambiar XDG_RUNTIME_DIR para PCSX2/PINE.
options=("--env=XDG_RUNTIME_DIR=$shared_runtime")
if [[ -n "${WAYLAND_DISPLAY:-}" && "$WAYLAND_DISPLAY" != /* ]]; then
    options+=("--env=WAYLAND_DISPLAY=$runtime/$WAYLAND_DISPLAY")
fi

echo 'Cierra primero las otras instancias de PCSX2 para que usen esta configuración.'
echo "Socket PINE esperado: $shared_runtime/pcsx2.sock"
exec flatpak run "${options[@]}" net.pcsx2.PCSX2 "$@"
