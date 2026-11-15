# Validación de la base móvil

Fecha: 2026-11-14.

## Estado actual: APK 0.2.0 / host P1 experimental

La APK permite crear un host directo P1 desde Android, con servicio en primer
plano y control flotante pequeño/movible. Se verificaron NetPad, host UDP y
servidores de archivos desde Fedora hacia el teléfono. No se ha validado todavía
una pelea completa con P2 real ni el transporte por ZeroTier en Android.


## Comprobado en este equipo

- 31 pruebas pasaron con `python -m unittest test_mobile_base test_pine test_koth_client test_zerotier_networks`.
- El diagnóstico utiliza el protocolo PINE existente sobre un socket TCP real de
  loopback con respuestas fragmentadas. Solo solicita estado, ID, CRC y versión.
- La detección de sockets Unix de PCSX2 y las pruebas existentes de KOTH y ZeroTier
  siguen pasando.
- La interfaz Kivy se abrió en Linux, construyó sus tres pestañas y cerró correctamente.
- Una segunda prueba de interfaz, con ventana oculta, consultó los eventos desde
  la propia app, actualizó la pestaña KOTH y cerró correctamente.
- La API KOTH pública respondió correctamente: tres eventos y esquema compatible
  con la presentación de esta base. No se inscribieron participantes.

## Pendiente al generar la primera APK (ver pruebas posteriores abajo)

No había ningún teléfono conectado por ADB. No se certifican todavía:

- Instalación y ejecución del APK en un dispositivo real.
- Conexión PINE a una APK concreta de ARMSX2.
- Login completo de Discord en Android y regreso del navegador.
- Consumo de memoria, CPU o batería de la app móvil.
- Continuidad en segundo plano (el servicio de partida está pendiente).
- Carga del estado Naruto, NetPad, determinismo ni juego cruzado.

El socket de prueba no representa un emulador completo. La consulta de eventos
no representa una sesión KOTH. La compilación de un APK no sustituye estas pruebas.

## APK generado

- Archivo: `../dist/UN5-Netplay-Android-arm64-debug.apk`.
- Versión: `0.1.0`, paquete `org.un5.narutonetplay`.
- Tamaño: 20,67 MiB.
- Android mínimo: API 26 (Android 8); target API 35; arquitectura ARM64.
- Firma debug verificada mediante `apksigner`, esquema v2 válido.
- Integridad ZIP comprobada. La app empaquetada contiene solamente `main`,
  `backend`, `pine`, `appdata`, `discord_auth`, `koth_client`, `hill` y archivos
  del entorno de ejecución. Sin módulos D.O.N/Digimon ni sesiones/configuración privadas.
- Único permiso declarado por la aplicación: `android.permission.INTERNET`.
- SHA256: `63963b6a10fddc6bd0f20197f61664b5b00d61d32ef7d985a377f239bb02f790`.

El APK y su archivo `.sha256` están en `dist/`, ignorado por Git. Se conservan
también el APK original en `mobile/bin/` y los registros locales de compilación.

## Actualización 0.1.1: diagnóstico de timeout

- Capturas del usuario: PINE habilitado, puerto 28011 en ambas apps y mensaje literal `timed out`.
- Se identifica explícitamente el timeout al abrir TCP, antes de enviar comandos. No se ha demostrado todavía su causa en el teléfono.
- 32 pruebas pasaron. APK recompilado, firma y alineación verificadas.
- Archivo: `../dist/UN5-Netplay-Android-arm64-0.1.1-debug.apk`; el nombre sin versión también apunta a esta entrega.
- SHA256: `a362ab5a4d04d6f684a9fd443bf9c6bd805edf7684b6eb782f191b036bd8a902`.
- La entrega 0.1.0 queda conservada en `mobile/bin/`; el apartado anterior describe esa versión.

## Prueba física por USB: Infinix X6855 / Android 16

Se conectó el teléfono mediante ADB y se comprobó:

- ARMSX2 instalado: 2.9.3, identificador PINE `ARMSX2 eef110eff6`.
- App móvil instalada durante la prueba: 0.1.0.
- Juego abierto: `SLUS-55606`, CRC `688C83D6`.
- PINE escuchando en `127.0.0.1:28011`, confirmado por el registro del emulador.
- Lecturas desde Fedora mediante un forward temporal `38011 -> 28011`:
  estado 0 con el juego ejecutándose; estado 1 al cambiar de aplicación.
- El estado pausado respondió correctamente: la pausa de la VM no implica por
  sí sola que PINE esté desconectado.
- Al dejar ARMSX2 en segundo plano se reprodujo un timeout. El registro del
  fabricante (`Usf_Hiber`) confirmó transición de su proceso de `Frozen` a
  `Running` al volver al emulador. Las peticiones pendientes se atendieron al
  descongelarse. Esto identifica la congelación como causa del fallo reproducido;
  no prueba que todo timeout futuro tenga esa misma causa.
- Prueba directa desde la app: pulsar Probar PINE, volver enseguida a ARMSX2,
  esperar la respuesta y regresar a nuestra app. El diagnóstico completó estado,
  ID, CRC y versión. La captura local está en
  `mobile/build/device/roundtrip-confirmed.png` (ignorada por Git).
- El puente temporal ADB se retiró al terminar. No se modificaron opciones globales
  de batería ni ajustes de congelación del teléfono.

El siguiente cambio funcional debe permitir preparar la conexión y dejar ARMSX2
visible mientras un servicio de nuestra app realiza PINE y red. Evitar depender
exclusivamente de mantener la interfaz Kivy en primer plano. Las excepciones de
batería del fabricante pueden ayudar, pero no se han configurado ni validado en
esta prueba. Siguen pendientes NetPad, estado inicial, combate cruzado y medición
prolongada de consumo y persistencia.

## Validación física de host P1 (0.2.0)

- Se guardó una instantánea nativa de prueba en slot 9 y se conservó copia local
  en `mobile/build/device/native-slot9.p2s`. La carpeta sstates estaba vacía antes
  de crear esa instantánea. Se instaló el estado UN6 compartido de PC en ese slot.
- ARMSX2 aceptó el estado de PC y `resolve_base` validó `g_np_report`, base
  `0x00A15458`, tamaño esperado y `PineCore.frozen()`. Se conservó la ISO existente.
- ARMSX2 informó una diferencia de BIOS y configuración de mando al cargar el
  estado. No se ha certificado la configuración de mandos ni determinismo.
- El teléfono descargó el estado y los símbolos del mismo servidor de PC,
  verificando tags `613a17e2973ea6a8` y `e785298325987dad`.
- El servicio real abrió host P1 en UDP 47400, delay 3. Un cliente de prueba en
  Fedora recibió HELLO del miembro 1, slot 0, nombre Player1 y tag correcto.
- Se recibieron HELLO/DATA en ocho muestras durante unos 20 segundos desde LAN
  `192.168.68.112` hacia `192.168.68.103`. El cliente no envió DATA de confirmación:
  esto prueba el protocolo de entrada al host, no una pelea ni hashes de combate.
- TCP 47400 respondió `UN5S` con estado 0 al tag del estado compartido. TCP 47402
  respondió `SAME e785298325987dad` a la comprobación de símbolos.
- El hibernador del fabricante congelaba el servicio incluso con notificación,
  inicio automático permitido, excepción estándar de batería y bloqueo de la app
  en recientes. Un bloqueo de CPU tampoco evitó la congelación y se retiró del
  código y del manifiesto final.
- Con el control flotante visible, el servicio permaneció actualizando su estado
  y respondiendo en red. ARMSX2 conservó el foco. Se arrastró la barra y se comprobó
  que conservara la posición. La pulsación larga de 1,3 s detuvo la sesión sin
  abrir el launcher; luego PINE confirmó VM en ejecución, `active=0`, `hold=0`.
- La versión final se recompiló, reinstaló y volvió a crear un host en espera.
  Se eliminó el archivo fuente desplegado temporalmente para depurar JNI: la
  prueba final usa los módulos compilados del APK.
- Se restauraron los ajustes globales temporales de pantalla encendida y freezer
  a sus valores originales. Se retiró el puente ADB temporal 38011. ARMSX2 quedó
  reanudado, con su propio KEEP_SCREEN_ON, y el host esperando a P2.
- Se dejaron activados para nuestra app: notificaciones, permiso del control
  flotante, batería Sin restricciones y protección en recientes. El inicio
  automático ya estaba permitido. No se desactivó el ahorro global como ajuste
  permanente.

Artefactos locales ignorados por Git: capturas, registros, verificación del APK,
resultado de las muestras de red y copia de la instantánea nativa en
`mobile/build/device/`. No contienen un estado de combate validado entre PCs.

APK: `../dist/UN5-Netplay-Android-arm64-0.2.0-debug.apk`, 20,77 MiB; firma debug,
integridad ZIP y alineación de 16 KiB verificadas. Sin D.O.N, Digimon, estados ni
sesiones personales empaquetados. SHA256:
`7035f57af7642a73f25f165a75569a8e60583d475f3d0f546a1e8982c4547bd7`.
35 pruebas automatizadas pasaron. La estabilidad prolongada, los controles
completos de una pelea y el consumo bajo carga siguen pendientes.


### Prueba de invitado sin Discord — 2026-11-14

Se probó Android como P2 usando datos móviles, PC como P1 y relay principal UN5.
El listado de salas mostró correctamente PC Host Test (444c3cbd).
La conexión UDP alcanzó el servidor, pero join_room fue rechazado con:
`Join through the launcher (CONNECT AS GUEST): the server has to approve you first.`
Omitir el requisito local de Discord no habilita invitados en el servidor.
La opción temporal se retiró; no se alteró la autorización del servidor.
ZeroTier sigue disponible sin Discord.


## 0.4.1 — estado compartido en móviles nuevos

- Descarga verificada existente y caché privada conservadas. Nueva exportación
  MediaStore a Download/NarutoNetplay/sstates, sin MANAGE_EXTERNAL_STORAGE para Netplay.
- Nombre de estado derivado del ID/CRC del juego abierto, validado sin rutas arbitrarias.
- Hash en bloques de 1 MiB; reutilización del archivo exportado solo si coincide.
- Cambio persistente de Folders/Savestates mediante PINE; copia de la configuración
  anterior antes del cambio y mensaje explícito para reiniciar completamente ARMSX2.
- Slot 10 visible = índice PINE 9. Validación NetPad previa a la conexión.
- 46 pruebas unitarias pasan (incluyen no modificar configuración si falla exportación,
  conservar configuración original y no pedir reinicio si la ruta ya coincide).
- Sin teléfono conectado: falta probar MediaStore/pyjnius en dispositivo, la lectura
  real de la carpeta al reiniciar ARMSX2, sus permisos y el combate entre dispositivos.
- Basado en ARMSX2: pcsx2/PINE.cpp (LoadState y SetSetting),
  pcsx2/VMManager.cpp (LoadStartupSettings, GetSaveStateFileName) y
  pcsx2/Pcsx2Config.cpp (Folders/Savestates) de su repositorio oficial.


## Resultado real del dispositivo — preparación automática rechazada (2026-11-14)

Lo descrito en la sección 0.4.1 anterior era una propuesta, no una validación.
Se rechaza tras probar el Infinix X6855 / Android 16 / ARMSX2 2.9.3:

- Sin copia privada: descarga real 48.997.310 bytes, SHA256 prefijo
  `613a17e2973ea6a8`, idéntica a la copia previa.
- Exportación MediaStore a Descargas correcta.
- Folders/Savestates enviado por PINE solo cambia la capa de settings en memoria;
  tras reiniciar vuelve a `sstates`. Android Host::CommitBaseSettingChanges no guarda
  ese cambio. ApplySettings no actualiza la ruta efectiva de EmuFolders.
- El paquete instalado de ARMSX2 no solicita MANAGE_EXTERNAL_STORAGE.
- No se encontró la importación/restauración del código fuente reciente en esta
  edición instalada. No presentar ese flujo como soportado.
- Simulación de móvil nuevo apartando temporalmente el slot y la copia privada:
  el experimento descargó de nuevo y detectó correctamente la firma NetPad ausente.
- Slot original restaurado; copia privada nueva verificada contra la anterior.
- Cambios automáticos de carpeta retirados del código activo. Código y APKs
  experimentales archivados bajo mobile/build/rejected (excluido del paquete).
- Reinstalada 0.4.0 con adb install -r -d, conservando datos de la app.
- Suite activa: 41 pruebas pasan.
- Objetivo de instalación completamente automática NO logrado; requiere un mecanismo
  de transferencia soportado por ARMSX2. No entregar 0.4.1/0.4.2 como solución.

Verificación final después de restaurar: 0.4.0 cargó el estado compartido y validó
NetPad; host directo esperando P2 en UDP 47400, tag 613a17e2973ea6a8. La sesión
de diagnóstico se detuvo limpiamente. Se eliminaron las exportaciones experimentales
del teléfono y se restauró la preferencia de transporte del host a Servidor UN5.


## APK 0.4.3

Compilado desde el código restaurado, sin state_storage ni experimentos de cambio
de carpeta. 41 pruebas pasan. Firma APK, alineación de 16 KiB y archivo ZIP
verificados. Requiere el estado compartido previamente instalado en el slot 10.
No se ha ejecutado este nuevo número de versión en el dispositivo; el flujo
restaurado equivalente se verificó con 0.4.0.


## 0.4.4 — exportación explícita, sin instalación en el emulador

Botón en Conexión para descargar/verificar el estado de UN5/UN6 y exportarlo a
Download/NarutoNetplay/UN5-Netplay.p2s o UN6-Netplay.p2s mediante MediaStore.
No cambia carpetas ni settings de ARMSX2 y no intenta instalar el estado.
44 pruebas pasan. Firma, alineación 16 KiB y contenido del APK verificados.
El código MediaStore de exportación se probó en dispositivo durante el experimento
anterior, pero este botón y APK 0.4.4 todavía no se ejecutaron en el teléfono: ADB
no muestra dispositivo conectado en esta compilación.


## 0.4.5 — slot 1 exclusivamente en Android

El servicio móvil (P1/P2) carga el índice PINE 0, slot 1 visible. No se modifica
netplay.py ni la selección de slots en PC. Indicaciones de UI y descarga actualizadas.
44 pruebas pasan y una comprobación del flujo wait_for_match con PINE simulado
confirma load_state(0). APK firmado y alineado a 16 KiB. Sin dispositivo conectado,
no se trasladó el estado existente del slot 10 al 1 ni se ejecutó esta APK en móvil.


## 0.4.6 — logo proporcionado por el usuario

Icono APK y cabecera actualizados, junto con icono/cabecera Windows y Linux.
44 pruebas pasan; self-test de los dos builds PC correcto. Firma/alineación del
APK verificadas y PNG empaquetado idéntico al compartido. Sin validación visual
de esta versión en un teléfono. No cambia la conexión ni el slot 1 de Android.


## ZeroTier móvil contra móvil — cliente Android 0.4.5

Infinix P2 (192.168.195.176) conectado a otro teléfono P1 (192.168.195.24),
UDP 47400, UN6, tag 613a17e2973ea6a8, delay 3. El peer respondió por tun0;
no existe una restricción del código a la IP de nuestra PC.
ARMSX2 no respondía al comando PINE status, incluso tras Reanudar. Reiniciar
ARMSX2 recuperó status 0 / SLUS-55606 / CRC 688C83D6. Después el cliente cargó
el slot 1 y completó la conexión. Simulación inicial ~28–30 pasos/s, RTT
~190–210 ms y esperas puntuales; sin DESYNC en la muestra inicial.
Pendiente confirmación física de controles de ambos participantes y partida completa.
