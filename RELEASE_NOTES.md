# UN5 Netplay 0.1.1A — Windows y Linux

El launcher se distribuye en un único archivo por plataforma, con Python y sus
dependencias incluidos. Ya no hace falta instalar Python ni ejecutar los scripts
del proyecto por separado.

## Descargas

| Plataforma | Archivo | Tamaño aproximado |
| --- | --- | --- |
| Windows x64 | `UN5-Netplay-Windows-x64.exe` | 20 MB |
| Linux x86_64 | `UN5-Netplay-x86_64.AppImage` | 23 MB |

Los archivos `.sha256` adjuntos permiten verificar la integridad de cada descarga.

## Novedades de este build

- **Actualización automática al abrir:** detecta nuevas releases numeradas de GitHub,
  muestra el progreso de descarga, verifica SHA256 y reinicia con la nueva versión.
- Si no hay conexión o falla la descarga, se abre la versión instalada.

- **Windows:** ejecutable que abre únicamente el launcher. PCSX2 se inicia manualmente.
- **Linux:** AppImage que abre el launcher y PCSX2 instalado mediante Flatpak,
  conservando el arranque con la ruta compartida de PINE.
- Python, Tcl/Tk, Pillow y certificados TLS incluidos en ambos paquetes.
- Los procesos internos de netplay funcionan con el runtime incluido.
- Archivos temporales de STOP fuera del contenido de solo lectura del AppImage.
- Registros de arranque y mensajes de error para facilitar el diagnóstico.
- Icono propio en la ventana y en el ejecutable de Windows, con varios tamaños.
- Iconos del AppImage en las rutas estándar para su integración en el menú con AppImageLauncher.
- Scripts para generar nuevas compilaciones de Windows y Linux desde el código fuente.

## Antes de jugar

- Tener PCSX2 configurado con tu BIOS y juego.
- Habilitar **Settings → Advanced → Enable PINE**, con el slot **28011**.
- Tener el juego abierto antes de iniciar una sesión de netplay.
- Para los modos ZeroTier, tener ZeroTier instalado y estar autorizado en la red correspondiente.

PCSX2, BIOS y juegos se obtienen y configuran por separado.

## Windows

1. Descarga `UN5-Netplay-Windows-x64.exe`.
2. Abre PCSX2 manualmente y carga el juego.
3. Ejecuta el `.exe` para abrir el launcher.

Las preferencias, la sesión y el registro `launcher.log` se guardan en
`%APPDATA%\UN5 Netplay`.

## Linux

PCSX2 debe estar instalado mediante Flatpak con el identificador `net.pcsx2.PCSX2`.
Si todavía no lo tienes:

```bash
flatpak install flathub net.pcsx2.PCSX2
```

Cierra las otras instancias de PCSX2 antes de abrir el AppImage. Da permiso de
ejecución al archivo e inícialo:

```bash
chmod +x UN5-Netplay-x86_64.AppImage
./UN5-Netplay-x86_64.AppImage
```

Se abrirán PCSX2 y el launcher. Al cerrar el launcher, PCSX2 permanece abierto.
Las preferencias se guardan en `~/.config/UN5 Netplay` y los registros en
`~/.local/state/un5-netplay`, respetando las variables XDG correspondientes.

Si el sistema no puede montar el AppImage mediante FUSE:

```bash
./UN5-Netplay-x86_64.AppImage --appimage-extract-and-run
```

Si AppImageLauncher interfiere con la apertura:

```bash
APPIMAGELAUNCHER_DISABLE=1 ./UN5-Netplay-x86_64.AppImage
```

## Actualización

Esta es la primera compilación con actualizador. Si tienes un paquete anterior,
descarga el nuevo archivo de tu plataforma y reemplázalo manualmente una vez.
A partir de esta versión, las releases numeradas posteriores se detectan al abrir
el launcher y se descargan automáticamente. Las preferencias y sesiones se guardan fuera del ejecutable.
La descarga de estados y símbolos del servidor conserva su funcionamiento habitual.

## Validación realizada

- Linux: comprobados Python, Tcl/Tk, Pillow, TLS, la ventana del launcher y el proceso interno de netplay.
- Windows: comprobados el ejecutable, sus dependencias, la ventana y el proceso de netplay en un Wine limpio sin Python instalado.
- Pasaron las pruebas automatizadas de los puntos de entrada de ambas plataformas.
- Actualizador: probadas descargas incompletas o corruptas, SHA256, progreso,
  sustitución y reinicio sobre copias temporales; en Windows, mediante Wine.

Queda pendiente validar una partida completa y probar el ejecutable en Windows nativo.
