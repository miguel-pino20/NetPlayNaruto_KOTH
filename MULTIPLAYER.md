# Salas de 2–4 jugadores por Django y ZeroTier

Estado: coordinación implementada y red probada con un juego simulado de cuatro
mandos. El hook experimental de D.O.N pasó una prueba de 180 frames en PCSX2
2.8.2, además de las pruebas de su puente C/Python para 2, 3 y 4 jugadores.
Falta verificar el estado del combate y el determinismo entre emuladores;
el cliente bloquea este adaptador para online mientras solo tenga hashes de
controles. El launcher tiene una herramienta para preparar estados de D.O.N,
además de conservar su flujo de UN5/UN6 y KOTH.

## Responsabilidades

- Django asigna puestos estables P1–P4, identifica participantes mediante los
  tickets existentes y elige P1 como host. La IP de ZeroTier localiza el PC; no
  sustituye la identidad del participante.
- Los invitados envían su mando al host por UDP sobre ZeroTier. El host distribuye
  los controles. HTTP solo coordina la sala.
- El adaptador del juego captura controles, publica las entradas de todos los
  mandos, detiene el avance hasta disponer de todas ellas y calcula hashes del
  estado del juego. En D.O.N la barrera y los controles ya están implementados;
  por ahora sus hashes solo acreditan igualdad de las entradas.

Las salas están asociadas a un torneo existente para reutilizar sus tickets.
No cambian la cola, los puntos, los resultados ni los turnos de KOTH. Un KOTH con
cuatro contendientes simultáneos necesitará además reglas y resultados propios.

## API añadida a djToruney

Todos los endpoints requieren `Authorization: Bearer <ticket>` de un participante
activo del mismo torneo. Los puestos internos son 0–3; los miembros de red son
1–4. Cada puesto contiene un mapa `{port, slot}` de PS2 (ambos comienzan en 1).

| Método y ruta | Operación |
| --- | --- |
| `POST /api/netplay/sessions/` | Crear sala con `capacity`, `delay`, `manifest`; creador ocupa P1 |
| `GET /api/netplay/sessions/<uuid>/` | Consultar estado; solo miembros |
| `POST .../<uuid>/join/` | Reservar el primer puesto libre; repetir conserva el puesto |
| `POST .../<uuid>/sync/` | Enviar IPv4, puerto, manifest y disponibilidad |
| `POST .../<uuid>/start/` | Creador inicia cuando todos están listos |
| `POST .../<uuid>/leave/` | Invitado abandona antes del inicio |
| `POST .../<uuid>/close/` | Creador cierra la sala |

Crear requiere, por ejemplo, `{"capacity":4,"delay":3,"manifest":...}`.
`sync` requiere `{"address":"10.147.0.1","port":47400,"ready":true,"manifest":...}`.
La respuesta incluye `slot`, `players`, `manifest`, `session_epoch`, `ready`,
`can_start` y `status` (`lobby`, `running` o `closed`).

El manifest debe contener `game` (por ejemplo `don`), `crc` (8 hex), `disc_sha256`,
`state_sha256` y `symbols_sha256` (SHA256 completos), `adapter` (identificador
versionado), `emulator` (build exacta) y `pads` (lista ordenada de 2–4 mapas de
puerto/slot, sin duplicados). En el ejecutable verificado de D.O.N, los cuatro
mandos usan los slots 1–4 del puerto 1; libpad recibe los índices 0–3 del puerto 0.

El servidor compara lo declarado por los clientes; los adaptadores deberán
comprobar esos datos contra el PCSX2 y los archivos locales. Comparar el manifest
es una condición de compatibilidad, no una prueba de determinismo.

La presencia vence tras 15 segundos sin heartbeat. Si falta un participante,
`ready` pasa a false. No se reemplazan automáticamente jugadores, ni se migra el
host durante una partida. Para otra partida se cierra la sala y se crea una
nueva, con otra identidad. El cliente del juego deberá detenerse si pierde la
API durante ese plazo, cambia la sesión, se cierra la sala o `ready` pasa a false.

## Cliente de desarrollo

La migración `0012_multiplayer_sessions` debe aplicarse en Django antes de usar
la API. No se ha ejecutado contra la base de datos del usuario.

Con el ticket existente en la variable `UN5_HILL_TICKET` y un `manifest.json`
preparado con los datos reales:

```sh
python multiplayer_client.py --api-url http://localhost:8000 create --manifest manifest.json --capacity 4
python multiplayer_client.py --api-url http://localhost:8000 join UUID_DE_SALA
python multiplayer_client.py --api-url http://localhost:8000 watch UUID_DE_SALA --manifest manifest.json --address IP_ZEROTIER --ready
```

Cada participante mantiene `watch` abierto; hace heartbeat cada dos segundos.
Ctrl+C retira su disponibilidad. El creador puede usar otra terminal con
`start UUID_DE_SALA`, `status UUID_DE_SALA` o `close UUID_DE_SALA`. Estos comandos
solo coordinan: no cargan un save state ni ejecutan una partida de PCSX2.

`make_node(snapshot, core)` crea la red usando el roster autorizado por Django.
Rechaza el `PineCore` actual para cuatro jugadores. Un adaptador debe declarar
`max_players >= capacity` y `adapter_id` igual al manifest, y cumplir el contrato
`captured`, `publish` y `hashes` de `node.py`. También debe resolver su carga,
congelación, liberación y restauración del juego. La integración que llame a esta
función debe mantener los heartbeats y cerrar el nodo cuando la sala deje de
estar lista. No conectar este contrato directamente al hook de Naruto: su bloque
de memoria solo tiene dos entradas.

## Trabajo pendiente para D.O.N

1. Hecho: identificar la ISO latina y verificar versión/CRC, rutinas de mandos
   y detección local de cuatro puestos mediante PINE.
2. Hecho: hook propio para D.O.N, reserva de memoria al arrancar y puente PINE.
   Los símbolos de UN6 no se reutilizan en este juego.
3. Preparar los estados iniciales desde «Organícense» para 2, 3 y 4 humanos y
   comprobar menús, carga, combate y revancha entre emuladores con las mismas
   entradas. Implementar y validar hashes del estado de simulación.
   El primer perfil de 4 jugadores ya está capturado y verificado en
   `build/don/profiles/4p/20261107-225147/`: ZIP íntegro, hashes coincidentes,
   barrera activa en frame 0 y captura interna mostrando cuatro puestos JUGADOR
   en «Organícense». El perfil de 3 jugadores también está verificado en
   `build/don/profiles/3p/20261107-225442/`, con P1–P3 en JUGADOR y P4 FUERA.
   El perfil de 2 jugadores está verificado en
   `build/don/profiles/2p/20261107-225528/`, con P1–P2 en JUGADOR y P3–P4 FUERA.
   Los tres perfiles se restauraron en la instancia experimental PINE 28012 y
   pasaron 60 fotogramas de prueba local cada uno. Esto no acredita sincronía
   de combate entre emuladores. Informe: `build/don/restore-test-results.json`.
4. La interfaz ya solicita 2–4 jugadores al preparar el estado. Falta conectar
   las partidas de D.O.N a las salas y al flujo gráfico de arranque, probarlas
   entre PCs y generar nuevos paquetes de distribución.
5. Hecho: SHA256 de la ISO completa obligatorio en las salas nuevas. Las versiones
   japonesa y latina comparten ejecutable, pero sus datos pueden diferir.

## Ejecutable experimental y perfiles de 2–4 jugadores

`build_don.py` extrae el ELF de la ISO del usuario y compila código propio con
Clang para MIPS III. Genera `build/don/DON-loopback.elf` y `adapter.json`.
La ISO permanece intacta. El fuente no incluye bytes extraídos del juego.

La reserva de 64 KiB empieza en `0x5A6800`. Se desplaza a `0x5B6800` el comienzo
de SetupHeap (`0x1001D0`), la referencia usada para calcular el gran pool del juego
(`0x1365DC`) y el program break inicial de `sbrk` (`0x3BC354`). Este último era
independiente de SetupHeap: la primera prueba real detectó que sobrescribía el
hook; la comprobación del cliente rechazó activarlo. Después de corregir las tres
referencias, la reserva permaneció intacta y pasó la prueba real de 180 frames.

El hook intercepta la llamada de lectura en `0x138B14` y `scePadRead`. Las envolturas
preservan los registros de propósito general que el ABI de PS2 requiere en 128 bits.
El bloque `g_np4` tiene captura local, cuatro anillos de entrada y hashes de entradas.
El mando físico 1A proporciona el control local; el puesto de red se asigna aparte.
Los slots sin participante de red reciben mandos neutros para que no bloqueen la
barrera de cuatro sockets de Multitap. Esto no cambia automáticamente los puestos
del menú a CPU o desactivados: esa distribución forma parte del estado preparado.

```sh
python build_don.py "/ruta/Battle Stadium D.O.N Latino Final.iso"
python don_test_session.py prepare --target build/don/pcsx2-test-nueva
python don_test_session.py start build/don/pcsx2-test-nueva/session.json --foreground
```

La prueba usa una instancia separada, ajustes y tarjeta copiados y PINE 28012.
Ese número solo separa la prueba de la instancia habitual. La ventana de
preparación y `don_core.py` usan 28011 por defecto y permiten elegir otra ranura;
la carpeta de estados se busca según la instancia elegida. También se puede
preparar una instancia con `don_test_session.py prepare --pine-slot 28011`,
siempre que otra instancia no esté usando ya esa misma ranura.
Para usar el PCSX2 habitual debe arrancarse con el ELF experimental: seleccionar
28011 no instala el hook en una partida abierta con el ejecutable original.
`-datapath` en PCSX2 2.8.2 coloca los ajustes en la subcarpeta `PCSX2`. Flatpak
recibe permisos temporales para la carpeta de prueba y acceso de solo lectura
a ISO y BIOS; no se cambian sus permisos permanentes.

```sh
python don_core.py --pine-slot 28012 status
python don_core.py --pine-slot 28012 loopback --players 4 --frames 180
python don_core.py --pine-slot 28012 stop
```

Para preparar el estado desde el launcher fuente, usar **D.O.N · estado inicial
(2–4)**. También puede abrirse la herramienta con `python don_setup.py`.
Solicita obligatoriamente 2, 3 o 4 jugadores. Antes de capturar, dejar
«Organícense» con esa cantidad de puestos en JUGADOR y los restantes como CPU o
desactivados, y reanudar PCSX2 si está pausado. Captura en una ranura libre,
congela el hook en frame 0, comprueba el ZIP y devuelve el control al juego al
terminar. No sobrescribe estados anteriores.

Cada revisión se guarda junto a `adapter.json`, en
`profiles/<cantidad>p/<fecha-hora>/`, con estado, manifest, símbolos portables y
metadatos del perfil. `don_profiles.py` verifica que el estado esté congelado en
frame 0, contenga esta compilación del hook y declare la cantidad seleccionada.
Un estado de cuatro jugadores no se puede etiquetar como uno de dos o tres.
Todos los PCs de una sala deben cargar el mismo archivo de estado, byte por byte.

`build/don/profiles/catalog.json` registra los tres perfiles comprobados. Se
regenera con `python don_profiles.py --index build/don/profiles`. La creación
de salas con `multiplayer_client.py create --profiles build/don/profiles`
selecciona el perfil de la cantidad indicada por `--capacity` y verifica sus
archivos antes de usarlo.

Para repetir una prueba local sobre la instancia experimental abierta:

```sh
python don_core.py --pine-slot 28012 restore-test --players 2 \
  --profiles build/don/profiles \
  --state-dir build/don/pcsx2-test-4/PCSX2/savestates --frames 60
```

La prueba carga el estado en una ranura libre y devuelve el control local al
terminar. Requiere la instancia con el ejecutable experimental y su carpeta
de estados correspondiente. Puede repetirse con `--players 3` o `4`.

La interfaz y las listas de módulos para empaquetar están actualizadas; no se
han recompilado ni publicado AppImage/EXE nuevos. La herramienta gráfica y la
captura de estados no habilitan todavía una sesión online de D.O.N.

### Prueba entre dos instancias locales

`don_dual_test.py` restaura el mismo perfil de dos jugadores en dos instancias
aisladas, conecta dos nodos por UDP de localhost y aplica controles distintos
para P1/P2. Retiene las entradas futuras para detener ambas exactamente en el
mismo número de consultas de mandos y guarda estados/pantallas de comparación.
Los archivos de diagnóstico van a una carpeta nueva; usa ranuras libres y
elimina solo sus copias temporales verificadas, sin tocar los perfiles.

```sh
python don_dual_test.py \
  --sessions build/don/pcsx2-test-4/session.json build/don/pcsx2-peer-28013/session.json \
  --checkpoints 600 720 960 1200 1800 --output build/don/dual-test-nuevo
```

Ambas instancias deben estar abiertas con el ejecutable experimental. El caso
registrado en `build/don/dual-test-combat-1/report.json` verificó hashes de
entradas iguales durante 1800 fotogramas en PINE 28012 y 28013: selección,
escenario Going Merry y combate con movimiento, saltos y ataques. Las capturas
finales muestran contador 164 en ambas. La primera prueba sin movimientos de
combate está en `build/don/dual-test-1/report.json` (720 fotogramas).

**Resultado parcial:** transporte y aplicación de mandos comprobados; sincronía
de simulación no certificada. Hay diferencias de RAM y de presentación en las
capturas. La RAM completa incluye temporizadores, DMA y renderizado asíncrono;
sus diferencias no demuestran por sí solas desincronía del combate. Falta
identificar y comparar estado lógico del juego en un punto estable, verificar
revancha y probar ZeroTier entre PCs. Se mantiene el bloqueo de online del
adaptador hasta completar esa validación.

## Perfil y diagnóstico de D.O.N

El ejecutable de `Battle Stadium D.O.N Latino Final.iso` coincide byte por byte
con el de la edición japonesa analizada:

- Serial `SLPS-25675`, ejecutable `SLPS_256.75`, CRC PCSX2 `82EA02B7`.
- SHA256 ELF: `994e840123eb5a4cd5d13170a52fdca275dabb0a9f4585665b5d0fc67f9180c1`.
- SHA256 ISO latina analizada: `914a10fc9ea47c95c2e501d60d7f5470d392f42e934ce079a358dc0255b53019`.
- Validación en PCSX2: modo Multitap 1, cuatro puestos, inicialización 99 y
  estado libpad 6 en los cuatro. Esto acredita la detección de mandos; aún no
  demuestra sincronización de una partida por red.

```sh
python don_adapter.py inspect-iso "/ruta/Battle Stadium D.O.N Latino Final.iso"
python don_adapter.py probe --pine-slot 28011
```

Estos comandos no escriben en la ISO ni en la memoria del juego. El diagnóstico
verifica serial, CRC y hashes de tres rutinas antes de leer las estructuras de
mandos. Rechaza versiones distintas y código modificado. Las lecturas no son
atómicas. El contador de VBlank pendiente en `0x4D6A08` se reinicia tras cada
consulta de mandos; no sirve como contador monotónico para lockstep.

Direcciones comprobadas en el ELF: `scePadRead` en `0x118E38`, consulta general
de mandos en `0x138FB0` (llamada en `0x138B14`), consulta Multitap en `0x255EA0`,
modo en `0x4D69E8`, cantidad en `0x4D69F8` y registros en `0x4D6A80`, separados
por `0x4C` bytes. El juego consulta el Multitap del puerto 1 y abre sus cuatro
slots cuando está presente. El puerto 2 no activa esa ruta de cuatro jugadores.

Referencias usadas para contrastar el análisis local:
[mapa del ejecutable](https://github.com/dvilelaf/battlestadium-don/blob/main/docs/knowledge/02-ps2-executable.md),
[mandos y Multitap](https://github.com/dvilelaf/battlestadium-don/blob/main/docs/knowledge/05-audio-video-input.md),
[cálculo del CRC en PCSX2](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/Elfheader.cpp).

El cliente PINE también busca el socket en
`$XDG_RUNTIME_DIR/.flatpak/net.pcsx2.PCSX2/xdg-run/pcsx2.sock`, ubicación observada
con el Flatpak actual, conservando las rutas anteriores.

## Guardado desbloqueado

El archivo del usuario `battle-stadium-don.12459.psu` contiene el directorio
`BISLPS-25675game`, correspondiente al identificador del juego. Se importó con
MyMC++ 3.2.0 a una tarjeta nueva de 8 MiB, `saves/DON-Latino-desbloqueado.ps2`
(8,650,752 bytes incluyendo ECC). La comprobación del sistema de archivos no
detectó errores. Se colocó una copia en la carpeta `memcards` del PCSX2 Flatpak;
no se sobrescribieron tarjetas ni se cambió la selección del emulador.

Para usarla, detener el juego, abrir sus ajustes de Memory Cards y seleccionar
`DON-Latino-desbloqueado.ps2` en la ranura 1. Después arrancar la ISO desde cero,
sin restaurar un save state anterior. El juego debe leer la tarjeta para cargar
el progreso. El usuario confirmó con una captura la carga de los personajes
desbloqueados. Las tarjetas y el guardado del usuario no se distribuyen en el repo.

El `.psu` es un paquete de guardado para importar en una tarjeta, no un estado
`.p2s` que se pueda cargar desde los atajos de PCSX2. Referencia:
[importación de guardados en PCSX2](https://pcsx2.net/docs/configuration/memcards/).

## Verificación

`python -m unittest test_multiplayer` comprueba cuatro nodos por UDP local y con
pérdida y reordenamiento de datagramas simulados, autoría de cada mando, hashes y el
contrato del cliente. La suite de Django `home.test_multiplayer` verifica
asignación, permisos, compatibilidad, caducidad y cierre. Estas pruebas no
establecen compatibilidad real de D.O.N ni sustituyen una prueba con PCSX2.
