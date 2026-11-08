# Comparación de D.O.N Japón y Latino

Comparación local del 8 de noviembre de 2026, con lectura de ambas imágenes completas y SHA-256 de cada archivo ISO9660. No se ejecutó PCSX2, no se modificaron las ISO y no se generaron builds ni estados nuevos.

| Elemento | Resultado |
| --- | --- |
| Serie | Ambas: `SLPS-25675` |
| CRC del ejecutable | Ambas: `82EA02B7` |
| Ejecutable `SLPS_256.75` | Idéntico, SHA-256 `994e840123eb5a4cd5d13170a52fdca275dabb0a9f4585665b5d0fc67f9180c1` |
| `SYSTEM.CNF`, `DIR.DIR` y todos los archivos de `MODULES/` | Idénticos |
| `BGM.AFS`, `DATA.AFS`, `MOVIE.AFS`, `SE.AFS` | Contenido diferente |
| Ubicación física de archivos comunes | 28 archivos están en sectores distintos |
| Relleno de disco | Japón contiene `DUMMY.DAT`; Latino contiene `DUMMY.BIN` |

SHA-256 de la ISO japonesa: `f447b25387e36393eff0cfbee9092c378f1ac1a2588dd183bb8b86b54a69c29b`.

SHA-256 de la ISO Latino: `914a10fc9ea47c95c2e501d60d7f5470d392f42e934ce079a358dc0255b53019`.

## Qué se conserva

El adaptador y su ELF local pueden conservarse: el ejecutable fuente y las funciones interceptadas coinciden. También se verificó el hash del ELF de arranque existente antes de preparar `build/don/japan/adapter.json`, que conserva el adaptador y apunta a la ruta y hash de la ISO japonesa. No se recompiló el ELF ni se cambió el descriptor Latino.

El `.psu` y la memory card local contienen `BISLPS-25675game`, el mismo identificador que corresponde a ambas versiones. El ejecutable y los módulos `MCMAN.IRX` y `MCSERV.IRX` son idénticos. Por tanto se puede conservar el guardado desbloqueado y usar la misma tarjeta. La lectura de los desbloqueos desde la japonesa aún debe comprobarse arrancando el juego normalmente; esta comparación no ejecutó una partida ni alteró el guardado.

## Qué debe capturarse nuevamente

Los perfiles actuales de 2, 3 y 4 jugadores identifican exclusivamente el hash de la ISO Latino. Los `.p2s` contienen RAM de EE e IOP, estructuras internas del emulador y recursos gráficos y de sonido. La igualdad del ejecutable no basta para validar la restauración del estado sobre otra imagen: los recursos y sectores de disco difieren.

Para cambiar a la japonesa, deben capturarse estados nuevos desde un arranque limpio de esa ISO con el adaptador activo y la misma memory card. No basta con cambiar `disc_sha256` en los manifest existentes. Mantener los estados japoneses separados en `build/don/japan/profiles/` y publicarlos solo cuando estén completos los perfiles de 2, 3 y 4 jugadores. Todos los jugadores deben utilizar la misma ISO que identifica el perfil publicado.

La captura requiere que PCSX2 esté abierto en la pantalla adecuada, con el adaptador activo. No se generaron estados en este análisis porque no se ha preparado esa pantalla desde el arranque japonés. El cambio de edición no demuestra que la causa de los bloqueos actuales sea la traducción.

El detalle completo por archivo y los hashes de las imágenes está en `build/don/iso-comparison-japan-latino.json`, generado localmente e ignorado por Git junto con los demás artefactos locales.
