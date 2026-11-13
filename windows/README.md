# UN5 Netplay para Windows x64

## Ejecutar el proyecto descargado con Git

Instala Python de Windows **de 64 bits, entre 3.11 y 3.15**, con Tcl/Tk y pip
(opciones normales del instalador de https://www.python.org/downloads/windows/).
Clona o actualiza el repositorio y abre **`1 - Run.bat`** desde su carpeta.

Durante el desarrollo se comparte y actualiza el codigo mediante Git, se
prueba en las dos maquinas y se compila/publica una release solo despues de
validar esas pruebas. No hace falta generar ni subir archivos de `dist/`
para probar cada cambio.

El script utiliza el codigo local y crea su propio entorno **`.venv-win`**.
Elige explicitamente una version compatible con **Pillow 13.0.0**, incluido
Python 3.15. Las dependencias se
descargan como paquetes precompilados: no necesitas instalar Visual C++ Build Tools.
Instala las dependencias de `windows/requirements-run.txt` solo cuando faltan o
no coinciden con las versiones declaradas. La primera preparacion necesita
Internet; despues puede abrirse con las dependencias ya disponibles.
La carpeta `.venv` de Linux no se utiliza ni se copia por Git. Si se encuentra
un `.venv-win` que no funciona en esa maquina, se conserva como copia de respaldo
y se crea uno nuevo.

Si fallo la instalacion anterior con Python 3.15 y Pillow 12, actualiza el
proyecto por Git y vuelve a abrir `1 - Run.bat`. El entorno de Python 3.15 se
reutiliza y Pillow se actualiza a 13.0.0; no hace falta cambiar de Python.

El arranque no descarga ni sobrescribe fuentes desde GitHub, no compila un EXE
y no abre PCSX2. Abre PCSX2 manualmente, carga el juego y activa PINE antes de
conectar una partida. Los datos y registros del launcher se guardan en
`%APPDATA%\UN5 Netplay`. No copies sesiones personales ni entornos virtuales
entre maquinas; inicia sesion con tu cuenta en el Windows de destino.

## Ejecutable independiente

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

Con Python de Windows x64 (3.11 o posterior) instalado y acceso a Internet,
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

Con el prefijo del proyecto preparado en `.windows-cache/wine` y Python en
`C:\Python313`, ejecuta `./build.sh windows` (o `./build.sh` para ambas plataformas).
Necesita `python3 -m pip` en Linux. Comprueba los wheels contra las versiones de
`requirements-build.txt` y descarga en `.windows-cache/wheels` los que falten
antes de iniciar Wine. Si la caché está completa, funciona sin conexión.

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
