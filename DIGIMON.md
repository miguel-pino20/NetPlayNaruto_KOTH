# Digimon Rumble Arena 2 USA: cuatro mandos experimentales

El código incluye un adaptador propio para Digimon, captura de perfiles, salas Django independientes, descarga/cache de estados y transporte ZeroTier con puentes. No se ha comprobado una partida online entre equipos: los hashes verifican entradas y todavía no certifican el estado de combate.

## Edición analizada

- ISO: `Digimon Rumble Arena 2 (USA).iso`.
- Serie: `SLUS-21067`; CRC original: `568A5C78`.
- SHA-256 del ejecutable: `590f453c7e39faeec8a2e46352b2655a18d1eb6e12fe693fe75583efcd15dacd`.
- SHA-256 de la ISO: `bbe7ded9ce352e4ccb83a2a2c62f7518792dda069382cd852b3656959016b0cb`.
- Versión observada por PINE: `PCSX2 v2.8.2`.

La lectura de PINE confirmó el orden de las ocho estructuras: `1A, 2A, 1B, 2B, 1C, 2C, 1D, 2D`. Había cinco conectores habilitados: los cuatro del puerto 1 y el principal del puerto 2. La configuración que el usuario confirmó funcional usa **1A, 2A, 2B y 2C**. El adaptador utiliza esa distribución y filtra únicamente los conectores sobrantes; el puerto 2 queda disponible. El orden lógico de los jugadores en la selección de personajes requiere confirmación visual al preparar los perfiles.

Cada PC captura su mando físico **1A**; el puesto de la sala determina a cuál de los cuatro mandos virtuales se envía. Al salir se desactiva el intercambio online y vuelven los mandos locales de esos cuatro conectores. La ISO y el arranque normal mantienen su comportamiento original.

## Preparación local del administrador

Se generó únicamente el ELF local del adaptador en `build/digimon/adapter-v1/Digimon-netplay.elf`, junto con su `adapter.json`. El CRC de este arranque con el mapa corregido es `8D5C93F5`. La ISO permanece intacta. No se generó un build del launcher. La prueba local autorizada posteriormente se describe abajo.

Para preparar otra revisión desde el código fuente, el administrador necesita clang con soporte MIPS:

```sh
python build_digimon.py "/ruta/Digimon Rumble Arena 2 (USA).iso" --output build/digimon/otra-revision
```

La preparación también está disponible en **Digimon → Opciones de PCSX2 / administración → Preparar adaptador Digimon desde tu ISO**. Esta selección de ISO es una tarea del administrador que crea los estados. Host e invitados normales solo necesitan el juego abierto y los descargan.

El ELF reserva memoria antes de iniciar el heap y el asignador propio del motor, incorpora el bloque de cuatro mandos y sustituye las entradas de actualización, lectura y estado de mandos. No debe inyectarse su bloque sobre una partida normal que ya haya inicializado el heap.

### Estado común para salas de 2, 3 o 4 jugadores

Se captura una sola selección con P1 dentro y P2–P4 en JOIN IN. El cuadro de
preparación de Digimon captura siempre cuatro puestos. Al publicar, el launcher
deriva los tres descriptores que exige la API actual de Django, con exactamente
el mismo archivo `state.p2s` y los mismos símbolos. Solo cambia el mapa de
puestos participantes del manifest; no se capturan tres estados distintos.
Al cargar, el launcher adapta la cantidad de jugadores mientras el hook sigue
congelado en frame cero y mantiene neutrales los puestos sin participante.
La caché de PCSX2 reutiliza el mismo estado entre cantidades de jugadores.

El estado común capturado en `profiles/4p/20261108-160902-open/` se publicó para
las tres capacidades en `https://narutimateonline.sytes.net` y se descargó con
verificación de paquete, estado y símbolos. Su SHA-256 es
`39a97359bb56a9b5a53a3386d637fe9ea81692085150843654ec9fbc2bb8b64c`.
Los resultados están en `build/digimon/shared-state-publication-result.json` y
`build/digimon/shared-state-pcsx2-check.json`. La carga real en PCSX2 comprobó las
tres capacidades congeladas en frame cero. Todos los participantes deben
reiniciar un launcher con este código antes de probar; los clientes anteriores
rechazan el estado común en salas de dos o tres. Sigue pendiente comprobar la
incorporación con Start o X y una partida entre equipos.

### Capturar el estado para cuatro jugadores

1. Cerrar la sesión de netplay y el PCSX2 normal para liberar PINE 28011.
2. Arrancar la misma ISO usando el ELF preparado. En Linux está el acceso local `build/digimon/adapter-v1/Abrir Digimon con adaptador.sh`, que reutiliza el PCSX2 Flatpak y su configuración. También se puede configurar manualmente el arranque con ELF en PCSX2.
3. Mantener PINE 28011, Multitap solo en el puerto 2 y cuatro DualShock 2 en **1A, 2A, 2B y 2C**. Mantener **2D desconectado**. Llegar a la selección de personajes con P1 dentro y P2–P4 en JOIN IN. Se puede usar la memory card existente; no hacen falta todos los personajes desbloqueados.
4. En el launcher actualizado, abrir **Digimon Rumble Arena 2 → Opciones de PCSX2 / administración → Preparar otro estado inicial**. Seleccionar **4**, el `adapter.json` de Digimon y la carpeta `sstates` de esa instancia. Capturar.
5. Publicar el estado común. El launcher usa la captura de cuatro puestos para las salas de 2, 3 y 4 jugadores. Se guarda en una carpeta diferente a la de D.O.N.

Se capturó y validó el estado de cuatro jugadores desde la selección confirmada por el usuario con el ELF `8D5C93F5`. Está en `build/digimon/adapter-v1/profiles/4p/20261108-151456/`, junto con manifest, símbolos y `Digimon-4p.zip`. El SHA-256 del estado es `a029b3ceaa7cae69bc0ade0281fc16da4c2612cb7b619a1c4906a78989624b17`. No se renombraron estados de D.O.N. Tras actualizar Django, el perfil de cuatro jugadores se publicó en producción el 8 de noviembre de 2026 a las 15:21 UTC. Se descargó desde `/api/netplay/digimon/profiles/4/state/` y se verificaron los hashes del paquete, estado y símbolos. El paquete tiene SHA-256 `886526888bcc434a724aa28be84d984ef91c6a9941c4256fc697725437af79d1` y tamaño 8 069 607 bytes. El resultado está en `build/digimon/production-profile-upload-result.json`.

## Servidor Django y conexión

Actualizar el proyecto Django, aplicar `python manage.py migrate` y reiniciar el servicio. La migración nueva es **0016_digimon_profiles**. `DigimonProfile` mantiene los paquetes centrales independientes; el campo de juego de las salas impide mezclar las rutas de D.O.N y Digimon. La API usa `/api/netplay/digimon/` y conserva la misma autenticación del launcher.

Una vez publicado el estado, todos deben actualizar el código por Git y reiniciar el launcher. El host selecciona Digimon y cuatro jugadores; los invitados entran con el código corto o IP. Todos deben usar la misma ISO y versión de PCSX2. Los invitados no necesitan clang ni el ELF local: el estado descargado contiene el adaptador.

Los registros están en `logs/digimon/` dentro de la carpeta de datos del launcher; el botón **Registros…** abre la carpeta. Si se detiene durante la carga, conservar los archivos de todos los equipos de ese mismo intento.

## Diagnósticos de solo lectura

```sh
python digimon_adapter.py inspect-iso "/ruta/Digimon Rumble Arena 2 (USA).iso"
python digimon_adapter.py probe --pine-slot 28011
```

Estos diagnósticos reconocen el arranque original sin el hook. Verifican la identidad y las huellas del código antes de leer estructuras. El diagnóstico vivo se guardó en `build/digimon/pine-probe-20261108T075212.458628Z.json`; el análisis estático está en `build/digimon/iso-analysis.json`. Son artefactos locales ignorados por Git.

Las funciones localizadas por análisis estático son lectura `0x003F2F18`, estado `0x003F3080`, decodificación `0x003ED650` y actualización global `0x003EDFD0`. La reserva de Digimon empieza en `0x00580000`, con 64 KiB; el heap se desplaza a `0x00590000`. Las posiciones y los estados de D.O.N no se usan como si fueran de Digimon.

## Validación pendiente

El arranque, la incorporación de cuatro puestos y la captura/restauración del perfil ya se comprobaron. Sigue pendiente conseguir el mismo avance del juego en cada instancia y validar una sesión entre equipos que atraviese menús, carga y combate. La preparación del código y del ELF no acredita que el juego ya funcione online de forma estable.

### Prueba local con un solo mando físico

Con el PCSX2 principal ejecutando el ELF preparado, PINE 28011 y ninguna sesión de netplay activa:

```sh
python digimon_local.py --seconds 100
```

Este diagnóstico para Linux/Flatpak abre tres instancias temporales con PINE 28012–28014. Reutiliza el mando físico de P1 y envía confirmaciones programadas para personaje, potencia y listo en P2–P4. Usa UDP local y el protocolo de cuatro nodos; no crea salas Django ni comprueba enlaces entre equipos por ZeroTier. Rechaza ranuras PINE temporales ocupadas, copia las tarjetas de memoria para cada instancia y respalda P1 antes de cargar el perfil. Al terminar desactiva el adaptador y cierra los grupos de procesos temporales completos.

Cada intento guarda `report.json`, registros de arranque y estados/capturas de comparación dentro de `build/digimon/local-4p-*`, fuera de Git. Crear el archivo `STOP` dentro de esa carpeta solicita terminar la prueba. Si se bloquea, también intenta guardar estados de diagnóstico. `completed` indica que terminó el ejercicio de transporte y alcanzó el punto de comparación; **no acredita sincronización del juego**.

La prueba del 8 de noviembre detectó un bloqueo intermitente: P2 dejó de capturar mientras los otros tres nodos esperaban sus entradas, aunque continuaban recibiendo paquetes UDP. Se corrigió además la limpieza de procesos temporales, que podía dejar descendientes de Flatpak después de terminar el proceso lanzador. Las edades de paquetes de los registros ahora convierten correctamente el reloj de milisegundos a segundos.

Las capturas del mismo fotograma 600 en `build/digimon/local-4p-session-04/` mostraban P1 en selección de arena y P2 en carga, pese a coincidir los hashes de entradas. La investigación posterior encontró diferencias en la preparación de esas instancias, por lo que ese resultado no demuestra por sí solo un defecto de sincronización de la simulación.

#### Aviso de compatibilidad y corrección del entorno local

La captura solicitada por el usuario confirmó el aviso `Compatibility Patches are not enabled`. El diagnóstico desactivaba esos parches únicamente en los clones. Se eliminó esa anulación para conservar el ajuste configurado en el PCSX2 principal.

El registro `build/digimon/warning-capture-01/startup.log` también registró `Failed to read ELF being loaded: host:Digimon-netplay.elf` y el cambio del CRC activo a cero después de cargar el estado. Los clones habían renombrado el ELF como `Digimon-local-P2.elf`, pero el estado conserva el nombre original. Ahora cada carpeta temporal conserva `Digimon-netplay.elf`; las instancias se distinguen por carpeta y ranura PINE. Los clones guardan su `logs/emulog.txt` y esperan a que el juego inicialice el mando antes de cargar el perfil.

Con esas correcciones, `build/digimon/local-matched-boot-02/` completó la comparación: las cuatro instancias llegaron a la misma selección de arena en el fotograma 600 y coincidieron en la transición observada en el 1200. El aviso de parches desactivados y el error de lectura del ELF no aparecen en su registro. Esto corrige el montaje de la prueba; aún no acredita sincronización de combate ni funcionamiento entre equipos. En particular, todavía debe validarse el invitado que arranca directamente la ISO original, porque el estado conserva una referencia al ELF preparado.

Para repetir el recorrido sin intervención del mando físico y guardar varios puntos exactos:

```sh
python digimon_local.py --scripted --checkpoints 600 1200 2400 --seconds 95
```

En este modo se programan confirmaciones para los cuatro puestos y movimientos/ataques distintos a partir del fotograma 1400. Las capturas y diferencias de RAM son evidencias de diagnóstico; no se interpretan como un checksum validado del combate.

La ejecución `build/digimon/local-matched-combat-01/` terminó 95 segundos de transporte sin desconexión y verificó más de 3000 hashes de entradas. Los cuatro emuladores alcanzaron combate, pero las capturas del fotograma 2400 muestran diferencias de posición y temporizador (2:52 frente a 2:53). Por tanto, subsiste una divergencia durante el combate, incluso después de corregir el entorno local. No se certifica el juego online ni se modificó el perfil publicado. Una prueba diagnóstica previa que forzaba un solo paso de simulación se guardó únicamente en copias locales; el perfil original se restauró y esa modificación no se incorporó al adaptador.

### Corrección de la reserva del asignador del juego

El primer arranque del adaptador se detuvo en el aviso de autoguardado. PINE confirmó que el código del adaptador en `0x00580000` había sido sustituido por datos mientras los saltos de las funciones seguían apuntando a esa zona. El cambio inicial de SetupHeap y sbrk no protegía esa memoria frente al asignador independiente del juego.

La revisión corregida desplaza a `0x00590000` las cinco referencias de ese asignador al antiguo final de imagen, dejando intacta la referencia usada para limpiar la BSS. El descriptor y los símbolos portátiles incluyen `arena_reservation: 2`. Tanto el driver como la validación de estados comprueban esta reserva; no se reutilizan capturas de la revisión anterior.

El nuevo CRC del ELF es `CDF9B30F`. Hay que cerrar el PCSX2 iniciado con el ELF anterior y arrancarlo de nuevo con el mismo acceso local. La corrección todavía necesita confirmación en ejecución después de ese reinicio; no se ejecutó una partida de prueba. Las lecturas que localizaron el problema se guardaron como `build/digimon/startup-diagnostic-*.json` y `startup-memory-*.json`.

### Incorporación con un solo mando físico

El cuadro de captura incluye **Incorporar jugadores con un solo mando**, para usar en selección con P1 dentro y los demás puestos OPEN. Crea un respaldo antes de enviar pulsaciones, conserva P1 neutral y restaura los controles locales después. La pantalla debe confirmarse antes de capturar un perfil.

En modo DualShock 2 `0x79`, Digimon decodifica X desde su presión analógica (byte 14), no solo desde el bit digital. La pulsación de preparación debe incluir ambos. Una lectura durante la pulsación confirmó el valor de presión convertido a `1.0` en el objeto del conector 1B, offset `0x28`; eso demuestra la llegada a la decodificación del mando, pero no confirma por sí solo la incorporación de un jugador en la pantalla.

### Mapa corregido del Multitap

El usuario comprobó la distribución funcional con la ISO original y el Multitap en el puerto 2: 1A para P1 y 2A/2B/2C para los otros puestos, dejando 2D desconectado. La hipótesis anterior de usar exclusivamente 1A–1D se descartó. El adaptador, los perfiles y la API ahora verifican el mismo mapa; D.O.N conserva el suyo.

El descriptor portátil de Digimon requiere `pad_layout: "port2"`. No deben reutilizarse los estados ni descriptores de la distribución anterior. La nueva preparación local conserva el nombre `Digimon-netplay.elf`, con CRC `8D5C93F5`; el acceso `.sh` existente carga esa revisión al reiniciar PCSX2. La revisión anterior se conserva en `build/digimon/archive/`. El usuario confirmó el arranque de esta revisión, dos mandos físicos y la incorporación virtual de P3/P4. El estado de cuatro jugadores ya se capturó, publicó y descargó con verificación de integridad. Queda validar una partida entre cuatro equipos.

Si ya se incorporaron dos jugadores físicos, seleccionar **Primer puesto que sigue OPEN: 3** para enviar pulsaciones únicamente a P3/P4 y conservar las elecciones de P1/P2. Por CLI se utiliza `--first-player 3`.
