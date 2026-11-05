# AppImage de UN5 Netplay para Linux x86_64

El archivo distribuible es `dist/UN5-Netplay-x86_64.AppImage`. Incluye el launcher,
Python 3.12, Tcl/Tk, Pillow y certificados TLS. **PCSX2 no va incluido**: se abre
la instalación Flatpak mediante `2 - PCSX2 Flatpak.sh`, con la misma ruta compartida
para el socket PINE que al usar los scripts por separado.

## Para el jugador

Instala previamente PCSX2 mediante Flatpak:

```bash
flatpak install flathub net.pcsx2.PCSX2
```

Recibe únicamente el `.AppImage`, dale permiso de ejecución y ábrelo:

```bash
chmod +x UN5-Netplay-x86_64.AppImage
./UN5-Netplay-x86_64.AppImage
```

Se abren PCSX2 y el launcher. Configura tu BIOS y juego en PCSX2 y habilita
**Settings → Advanced → Enable PINE**, slot **28011**, como con los scripts.
Cierra antes otras instancias de PCSX2 para que use la configuración del script.
El modo ZeroTier sigue requiriendo ZeroTier instalado y conectado a la red.
Al cerrar el launcher, PCSX2 permanece abierto.

Los datos del jugador se conservan en `~/.config/UN5 Netplay` (o `XDG_CONFIG_HOME`).
La carpeta de save states se selecciona desde el launcher si no se detecta;
la ubicación habitual del Flatpak es `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/sstates`.
Los registros quedan en `~/.local/state/un5-netplay` (o `XDG_STATE_HOME`).

En sistemas que no puedan montar AppImages mediante FUSE:

```bash
./UN5-Netplay-x86_64.AppImage --appimage-extract-and-run
```

Si AppImageLauncher intercepta la apertura y muestra un diálogo o un error de Qt,
puedes omitir esa integración sin cambiar el sistema:

```bash
APPIMAGELAUNCHER_DISABLE=1 ./UN5-Netplay-x86_64.AppImage
```

No se necesita Python instalado, un entorno virtual, pip ni los `.sh` externos.
El AppImage no instala paquetes del sistema. Al abrirse, comprueba las releases
de GitHub y descarga una versión posterior si está disponible, verificándola
antes de reemplazar el archivo y reiniciar el launcher.
Consulta [actualizaciones automáticas](../UPDATES.md) para publicar nuevas versiones.
No incluye BIOS, juegos, sesiones ni
configuración personal del equipo que lo construye.

## Construcción

Desde la raíz del proyecto, con Python 3 y acceso a Internet:

```bash
python3 appimage/build_appimage.py
```

Las descargas se verifican con SHA256 y se guardan en `.appimage-cache/`.
Los archivos intermedios quedan en `build/appimage/`; no se cambia el Python
del sistema. La salida incluye el AppImage y su archivo `.sha256`.
Las versiones y hashes están fijados en `build_appimage.py` y `requirements.txt`.
Si las publicaciones `continuous` de AppImage cambian, hay que revisar y actualizar
su URL/hash; el constructor rechaza automáticamente una descarga diferente.

Se puede comprobar el paquete sin abrir ventanas ni iniciar PCSX2:

```bash
./dist/UN5-Netplay-x86_64.AppImage --self-test
```

La comprobación carga el launcher, Tcl/Tk, Pillow y certificados, y ejecuta
`netplay.py --help` con el Python incluido. No comprueba una partida real.

Fuentes de los componentes: [Python AppImage](https://github.com/niess/python-appimage),
[appimagetool](https://github.com/AppImage/appimagetool) y
[runtime de AppImage](https://github.com/AppImage/type2-runtime).
Se conservan los archivos y licencias de Python y sus dependencias incluidos en
la imagen de Python y en el wheel de Pillow.
