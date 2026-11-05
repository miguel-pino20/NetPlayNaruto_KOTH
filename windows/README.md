# UN5 Netplay para Windows x64

Comparte únicamente `dist/UN5-Netplay-Windows-x64.exe`.
El jugador lo abre con doble clic: inicia solo el launcher de netplay.
No ejecuta ni incluye PCSX2, Flatpak, `.sh` ni `.bat`.
Incluye Python, Tcl/Tk, Pillow y certificados TLS; no necesita instalar Python.
El contenido se extrae automáticamente en una carpeta temporal durante la ejecución.

El jugador abre PCSX2 por su cuenta, carga su juego y habilita PINE en el slot
28011, como al usar los scripts. Los modos ZeroTier necesitan ZeroTier instalado
y conectado a la red. Los datos de usuario y el registro `launcher.log` se guardan
en `%APPDATA%\UN5 Netplay`. No se incluyen cuentas, BIOS, juegos ni save states
personales del equipo que construye el ejecutable.

El programa no instala paquetes del sistema. Al abrirse, comprueba las releases
de GitHub y descarga una versión posterior si está disponible. Verifica la
descarga, cierra la versión anterior, reemplaza el `.exe` y reinicia el launcher.
Las descargas de estados y símbolos del servidor de netplay conservan su
funcionamiento habitual. Consulta [actualizaciones automáticas](../UPDATES.md).

## Construir en Windows

Con Python de Windows x64 (3.10 o posterior) instalado y acceso a Internet,
desde la raíz del proyecto:

```powershell
py windows/build_windows.py
```

El constructor crea un entorno virtual aislado en `build/windows/venv`, instala
las versiones fijadas en `windows/requirements-build.txt` y genera el `.exe`
con PyInstaller. Comprueba Tcl/Tk, Pillow, TLS y el proceso de netplay dentro
del ejecutable antes de generar su archivo `.sha256`.
No hace falta tener PCSX2 instalado para construir o comprobar el paquete.

Comprobaciones manuales, sin abrir PCSX2:

```powershell
.\dist\UN5-Netplay-Windows-x64.exe --self-test
.\dist\UN5-Netplay-Windows-x64.exe --smoke-test-gui
```

El segundo comando abre brevemente el launcher y lo cierra.
Estas comprobaciones no sustituyen una partida de prueba en Windows.

## Construir desde Linux mediante Wine

Se necesita Python **de Windows**, no el Python de Linux. Se puede instalar en
un prefijo Wine dedicado al proyecto, por ejemplo `.windows-cache/wine`.
Ejecuta el mismo constructor con ese Python mediante Wine; para construir sin
red dentro de Wine, `--wheel-dir` permite indicar una carpeta con los wheels
de Windows de PyInstaller, Pillow, certifi y sus dependencias.

Por ejemplo, si Python está instalado en `C:\Python313` dentro del prefijo:

```bash
WINEPREFIX="$PWD/.windows-cache/wine" WINEDEBUG=-all \
TCL_LIBRARY='C:/Python313/tcl/tcl8.6' TK_LIBRARY='C:/Python313/tcl/tk8.6' \
wine 'C:\Python313\python.exe' windows/build_windows.py --wheel-dir .windows-cache/wheels
```

Las rutas explícitas de Tcl/Tk evitan problemas de detección mediante la unidad
`Z:` de Wine. El ejecutable final lleva sus propias rutas y bibliotecas.

El ejecutable se compila con consola habilitada y oculta automáticamente cuando
posee su propia consola. Esto permite que los procesos internos conserven la
salida que muestra el launcher. El punto de entrada reconoce los comandos de
`netplay.py` y `pine.py`; no vuelve a abrir la interfaz al iniciar una pelea.
