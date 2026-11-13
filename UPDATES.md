# Actualizaciones automáticas de los compilados

Los paquetes de Windows y Linux consultan las releases públicas del repositorio
configurado al abrir el launcher, antes de iniciar netplay o PCSX2.
El código del actualizador está incluido desde **0.1.0A**.

Cuando existe una versión posterior para la plataforma actual:

1. Aparece «Nueva actualización … Descargando, espera…», con el progreso.
2. Se descargan el ejecutable y su SHA256 desde la misma release de GitHub.
3. Se verifican el tamaño, el hash y el formato del archivo.
4. Se reemplaza el compilado en su ubicación actual y se reinicia el launcher.

En Windows, un auxiliar espera al cierre del ejecutable anterior antes de
reemplazarlo. En Linux, se sustituye el AppImage conservando su ruta y permiso
de ejecución. Esto también permite conservar el acceso directo que apunta a él.
Al reiniciar, se omite una comprobación de actualizaciones para evitar otro ciclo
de arranque inmediato. Los procesos internos de netplay y PINE no ejecutan el actualizador.

Si no hay conexión, falla la descarga o no se puede escribir en la carpeta del
compilado, se abre la versión instalada. Un fallo de reemplazo o de lanzamiento
del archivo nuevo revierte el cambio. Se conserva una copia temporal del archivo
anterior hasta que la ventana nueva se ha creado.
Las preferencias, la sesión y los archivos del jugador no se reemplazan.
El diagnóstico queda en `updater.log`, dentro de la carpeta de datos de UN5 Netplay.

## Publicar una actualización

### Generar las notas

El script `generate_release_notes.py` usa Python 3.10 o posterior y Git local,
sin dependencias adicionales ni acceso a Internet. Lee la versión y los nombres
de los paquetes de `release_info.py` y genera un borrador:

```bash
python3 generate_release_notes.py
```

La salida predeterminada es `dist/RELEASE_NOTES-VERSION.md`; no modifica
`RELEASE_NOTES.md`. Busca la etiqueta de versión anterior alcanzable desde HEAD.
Si no hay etiquetas, busca un commit cuyo título sea una versión anterior,
como `0.1.5A`. Sin una referencia anterior, incluye todo el historial.
Los cambios se describen con los títulos de los commits y enlaces a GitHub.

Opciones útiles:

```bash
# Elegir el inicio del intervalo y añadir una descripción para los jugadores:
python3 generate_release_notes.py --since 0.1.5A --highlight "Migración automática del servidor anterior"

# Revisar también los archivos versionados con cambios pendientes de commit:
python3 generate_release_notes.py --include-uncommitted --stdout

# Guardar directamente en el archivo principal, reemplazando el contenido:
python3 generate_release_notes.py --output RELEASE_NOTES.md --force
```

`--since` acepta una etiqueta o un hash de commit existente. `--highlight` se
puede repetir. El script termina con un error si el archivo de salida existe,
salvo que se indique `--force`. En Windows, usa `py` en lugar de `python3`.
Revisa el borrador y completa la sección de validación: el generador no ejecuta
pruebas, no comprueba los binarios y no publica la release.

### Compilar y publicar

Edita `release_info.py` antes de compilar:

```python
VERSION = "0.1.2A"
REPOSITORY = "miguel-pino20/NetPlayNaruto_KOTH"
INCLUDE_PRERELEASES = True
```

Usa la misma versión en los dos builds y en la etiqueta de la release de GitHub,
por ejemplo `0.1.2A` o `v0.1.2A`. También se admiten versiones como
`0.1.2-alpha.1`, `0.1.2-beta.1`, `0.1.2-rc.1` y `0.1.2`.
La comparación es numérica: `0.1.10A` es posterior a `0.1.9A`.
Las etiquetas sin número, como `Alpha`, se omiten.
También se rechazan etiquetas como `Alpha0.1.1A`: el nombre visible de la
release puede ser descriptivo, pero su **tag** debe ser `0.1.1A` o `v0.1.1A`.
Si una publicación no aparece en el launcher anterior, comprueba primero ese
tag y los cuatro archivos adjuntos. Corregir solo el nombre visible no cambia
la etiqueta que consulta el actualizador.

1. Compila y comprueba las aplicaciones.
2. Crea una release en borrador en el repositorio configurado.
3. Adjunta los cuatro archivos, manteniendo estos nombres:

   ```text
   UN5-Netplay-Windows-x64.exe
   UN5-Netplay-Windows-x64.exe.sha256
   UN5-Netplay-x86_64.AppImage
   UN5-Netplay-x86_64.AppImage.sha256
   ```

4. Cuando hayan terminado de subir, publica la release.

El actualizador consulta la lista de releases, por lo que también admite las
marcadas como pre-release si `INCLUDE_PRERELEASES` es `True`. Ignora borradores,
versiones anteriores y releases que no tengan el archivo y su SHA256 para la
plataforma actual. Las descargas usan HTTPS y los servidores de GitHub.

La versión incluida en el compilado debe coincidir con su etiqueta. Cambiar solo
la etiqueta o volver a subir el mismo ejecutable no cambia su versión interna.
Puedes consultar la versión interna ejecutando el archivo con `--version`.
Mantén el repositorio y los nombres de los archivos para que las versiones ya
distribuidas puedan encontrar las siguientes actualizaciones.

## Primera instalación

Los compilados anteriores a esta implementación deben reemplazarse manualmente
una vez: no contienen código para buscar releases. A partir de la primera versión
con actualizador, las siguientes actualizaciones se descargan al abrir el launcher.

El actualizador afecta a los paquetes `.exe` y `.AppImage`. Ejecutar los módulos
Python directamente o un AppDir extraído no reemplaza los archivos del proyecto.
Las comprobaciones `--version`, `--self-test` y `--smoke-test-gui` omiten la búsqueda de releases.

## Pruebas del actualizador

Pruebas de selección de versiones, descargas, SHA256 y recuperación:

```bash
python -m unittest test_updater
```

Después de compilar, pruebas opcionales con ventanas y copias temporales de los paquetes:

```bash
# Linux, con sesión gráfica y permisos para ejecutar AppImages:
UN5_TEST_GUI_UPDATES=1 python3 -m unittest discover -s appimage -p test_update_integration.py
```

```powershell
# Windows, con Python instalado solo para ejecutar estas pruebas:
py -m unittest discover -s windows -p test_update_integration.py
```

No publican releases ni abren PCSX2. La prueba de Windows reemplaza una copia del
ejecutable mientras está abierto y comprueba el reinicio y la limpieza del respaldo.
