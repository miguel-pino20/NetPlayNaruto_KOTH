# UN5 Netplay 0.1.5A — Windows y Linux

Esta versión actualiza la dirección predeterminada del servidor de eventos y
salas, y corrige la preparación de las compilaciones de Windows desde Linux.

## Cambios de esta versión

- **Servidor predeterminado actualizado:** `https://narutimateonline.servegame.com/`
  para eventos KOTH y como dirección de respaldo de las salas D.O.N y Digimon.
- Las direcciones antiguas guardadas de KOTH, D.O.N y Digimon se migran al
  nuevo dominio, conservando los servidores personalizados y las credenciales
  de inscripción existentes.
- **Compilación de Windows corregida:** el script comprueba que la caché tenga
  las versiones requeridas, incluido Pillow 13, y descarga las dependencias
  faltantes antes de iniciar Wine. Con la caché completa puede compilar sin conexión.
- Documentación actualizada con la nueva dirección y las instrucciones de compilación.

## Descargas

| Plataforma | Archivo | Tamaño aproximado |
| --- | --- | --- |
| Windows x64 | `UN5-Netplay-Windows-x64.exe` | 20 MiB |
| Linux x86_64 | `UN5-Netplay-x86_64.AppImage` | 23 MiB |

Descarga el archivo de tu plataforma. Ambos incluyen Python y sus dependencias.
Los archivos `.sha256` adjuntos permiten verificar la integridad de las descargas.
PCSX2, BIOS y juegos se configuran por separado.

## Antes de conectar

- Configura PCSX2, carga tu juego y habilita **Enable PINE**, con el slot **28011**.
- Para los modos ZeroTier, instala ZeroTier y conecta el equipo a la red correspondiente.
- Reinicia el launcher actualizado para aplicar la migración de las direcciones
  guardadas. Si usas un compilado anterior, cambia el campo del servidor a
  `https://narutimateonline.servegame.com/` también en las salas D.O.N o Digimon.

**Windows:** abre PCSX2 manualmente y ejecuta el `.exe` para abrir el launcher.

**Linux:** requiere PCSX2 instalado mediante Flatpak (`net.pcsx2.PCSX2`).
Cierra otras instancias de PCSX2 y ejecuta:

```bash
chmod +x UN5-Netplay-x86_64.AppImage
./UN5-Netplay-x86_64.AppImage
```

El AppImage abre PCSX2 y el launcher. Si el sistema no puede montarlo mediante FUSE,
usa `--appimage-extract-and-run`. Si AppImageLauncher interfiere con la apertura,
ejecútalo con `APPIMAGELAUNCHER_DISABLE=1`.

## Estado experimental

Las salas D.O.N y Digimon para 2–4 jugadores siguen siendo experimentales.
La coincidencia de los hashes de entradas no certifica la sincronización del
combate. Digimon tiene divergencias de combate documentadas en las pruebas locales;
sigue pendiente validar una partida completa entre equipos.

## Actualización y comprobaciones

Las versiones con actualizador pueden detectar esta release al abrir el launcher.
También puedes descargar y reemplazar manualmente el archivo de tu plataforma.
Las preferencias y sesiones se guardan fuera del ejecutable.

Se generaron ambos paquetes y se verificaron sus SHA256. Pasaron las comprobaciones
internas de Python, Tcl/Tk, Pillow, TLS, importación del launcher y proceso de netplay.
El ejecutable de Windows se comprobó mediante Wine. Estas comprobaciones no incluyen
una partida completa ni una prueba de esta compilación en Windows nativo.
