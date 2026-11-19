# Viabilidad de KOTH de PC en móvil

Fecha: 15 de noviembre de 2026.
Alcance: análisis del código, los registros locales y los resultados de pruebas comunicados por el usuario. No se implementó ni modificó el funcionamiento de KOTH, Android, PC o Django. No se probaron dispositivos ni se consultaron servidores durante la redacción.

## Respuesta principal

**Sí, el método de KOTH puede adaptarse a Android, pero el flujo completo de PC no funciona trasladándolo tal cual.** La coordinación del torneo es reutilizable; la ejecución de combates, preparación del emulador y continuidad del servicio requieren adaptación y validación física.

La app Android actual solo consulta eventos KOTH. No integra inscripción, presencia continua, cambios de turno ni arranque automático de combates KOTH.

El análisis se refiere a **Android ARM64 con ARMSX2**, que es la plataforma móvil presente en el repositorio. No hay base para afirmar compatibilidad con iPhone/iPad ni con cualquier emulador de PS2.

## 1. Cómo funciona el método de PC

1. El launcher consulta eventos y permite inscribirse o introducir un código personal.
2. Conserva una credencial por sitio y evento para recuperar al participante. Puede vincularlo a Discord mediante verificación del servidor.
3. Prepara el estado y los símbolos, carga el estado en PCSX2 y comprueba NetPad antes de anunciar disponibilidad.
4. `hill.py` consulta periódicamente Django y comunica IP, puerto, juego, identificadores de archivos y disponibilidad.
5. Django decide la pareja y sus roles. La primera posición juega como host/P1 y la segunda como guest/P2.
6. En el flujo habitual, los controles viajan directamente por ZeroTier, UDP 47400, con delay 3. Django coordina; no transporta el combate.
7. Por cada combate o reproducción, `hill.py` lanza un proceso de `netplay.py` y lo detiene al cambiar el turno.
8. El organizador registra el ganador en Django. El ganador permanece delante y el perdedor pasa al final.
9. Los participantes en espera pueden recibir controles por TCP 47401 y reproducir el combate en su propio emulador.

No hay detección automática del ganador en este flujo. Tampoco se adjudica una victoria por una desconexión.

## 2. Qué existe y qué está probado en móvil

| Elemento | Evidencia local | Límite de esa evidencia |
|---|---|---|
| Consulta de eventos KOTH | Implementada en `mobile/main.py` y documentada en la validación | No equivale a participar en el torneo |
| Comunicación PINE con ARMSX2 | Probada en Infinix X6855 / Android 16 / ARMSX2 2.9.3 | Hubo congelaciones y fue necesario volver al emulador o reiniciarlo |
| Carga de estado de PC y firma NetPad | Documentada en dispositivo | Aceptar el archivo no certifica determinismo ni controles completos |
| Servicio de partida independiente de Kivy | Implementado para host y cliente | No contiene un coordinador KOTH |
| Host UDP y servidores de archivos | Respuestas verificadas desde Fedora | Un handshake no demuestra una pelea |
| ZeroTier entre dos móviles | Registro local de conexión y simulación inicial; posteriormente el usuario confirmó peleas completas con resultado perfecto | Resultado funcional reportado; sin nuevos registros técnicos adjuntos |
| ZeroTier con PC host y móvil cliente | El usuario confirmó peleas completas con resultado perfecto | No se adjuntaron mediciones ni comparación de hashes |
| ZeroTier con móvil host y PC cliente | El usuario reportó resultado negativo/incierto, con la partida trabada | Según el usuario, la causa fue la mala conexión del host móvil, no netplay; pendiente repetir en buenas condiciones |
| Control flotante y continuidad | Ayudó a mantener el servicio activo en el teléfono probado | No garantiza sesiones largas ni todas las marcas |
| Descarga/exportación del estado | Implementada y documentada | No instala el estado en el almacenamiento privado de ARMSX2 |

`mobile/VALIDATION.md` acumula pruebas históricas. Sus apartados iniciales que indican ZeroTier pendiente deben leerse junto con la prueba móvil contra móvil posterior y la actualización del usuario registrada a continuación. Las peleas completas reportadas confirman funcionamiento práctico en los escenarios exitosos, pero no certifican la coordinación KOTH.

### Actualización del usuario: peleas por ZeroTier del 14 de noviembre de 2026

Resultados comunicados el 15 de noviembre de 2026. El primer dispositivo de cada pareja fue **P1/host**; el segundo fue **P2/cliente**.

| P1 / host | P2 / cliente | Resultado comunicado |
|---|---|---|
| Móvil | Móvil | Peleas completas: perfecto |
| PC | Móvil | Peleas completas: perfecto |
| Móvil | PC | Negativo/incierto: trabado. El usuario atribuye el problema a la mala conexión del host móvil y señala que no fue causado por netplay |

Esta actualización reemplaza la consideración de pelea completa pendiente para móvil–móvil y PC host–móvil cliente. El tercer escenario queda pendiente de una repetición con buena conexión; no se registra como un fallo demostrado de netplay. No se aportaron logs, hashes, versiones, duración ni modelos de los equipos de estas pruebas. No se infiere que se hayan probado inscripción, cola o rotación automática de KOTH.

## 3. Lo que sí se puede llevar a Android

| Función | Viabilidad | Condición o adaptación |
|---|---|---|
| Consultar eventos | Ya disponible | Mantener compatibilidad con la API |
| Ver cola, puntos, pareja y siguiente jugador | Alta | Presentar las respuestas de Django en Kivy |
| Inscribirse como invitado | Alta | Integrar `enroll` y guardar la credencial local |
| Entrar con código personal | Alta | Protegerlo como credencial y verificarlo con Django |
| Recuperar la inscripción | Alta | Reutilizar `MembershipStore`; conservar datos de la app |
| Vincular Discord | Viable | Reutilizar verificación del servidor y validar el recorrido navegador/app |
| Mantener resultados y reglas en Django | Alta | No hace falta trasladar el servidor al teléfono |
| Descargar y comprobar estado y símbolos | Ya hay base | La copia descargada debe corresponder al estado instalado en el emulador |
| Preparar NetPad mediante PINE TCP | Hay base probada | Emulador compatible, visible y con estado correcto |
| Jugar como P1 o P2 | Peleas completas reportadas en móvil–móvil y PC host–móvil cliente | Repetir móvil host–PC cliente con buena conexión y validar cambios automáticos de rol |
| Jugar por ZeroTier móvil–móvil | Peleas completas con resultado perfecto, según el usuario | Falta medir estabilidad prolongada y consumo |
| Jugar PC–móvil | Perfecto con PC host, según el usuario; resultado incierto con móvil host por mala conexión reportada | Repetir el segundo sentido y documentar hashes de simulación |
| Cambiar de rival automáticamente | Viable con adaptación | Detener la sesión anterior, liberar recursos, recargar estado y comenzar la nueva |
| Cambiar de P2 a P1 al ganar | Viable con adaptación | El móvil debe poder recibir al siguiente rival como host |
| STOP sin borrar inscripción | Viable | Detener combate y presencia; conservar la credencial y liberar NetPad |
| Notificar un turno | Viable | Integrar notificaciones sin exigir volver continuamente a Kivy |
| Espectar desde Android | Posible como fase posterior | Empaquetar dependencias, adaptar ejecución y comprobar reproducción determinista |

Viabilidad significa que el diseño y las piezas existentes permiten plantearlo; no significa que esas integraciones estén implementadas o aprobadas por una prueba real.

## 4. Lo que no funciona tal como está

### 4.1 Ejecutar directamente el coordinador de PC

`hill.match_command()` construye un comando con `sys.executable` y una ruta a `netplay.py`; `hill.run()` lo ejecuta mediante `subprocess.Popen`.

Ese modelo no está integrado en el entorno Android empaquetado. La app móvil existente llama a `netplay.main(argv)` desde su servicio. **Incluir `hill.py` en el APK no lo convierte en un KOTH operativo.** Se necesita un coordinador compatible con el ciclo de vida del servicio y sesiones que puedan iniciarse y terminarse de forma controlada.

No se afirma que Android prohíba todos los procesos: el problema concreto es trasladar sin adaptación este lanzamiento del intérprete y scripts de escritorio.

### 4.2 Copiar automáticamente el estado a ARMSX2 como en PC

`netplay.load_match_state()` pide guardar un slot, busca el archivo en una carpeta accesible y lo reemplaza por el estado compartido. Ese acceso no está disponible en el flujo Android probado.

PINE puede solicitar cargar un slot, pero no transferir el archivo a la carpeta privada del emulador. Las propuestas de cambiar `Folders/Savestates` mediante `SetSetting`/`ApplySettings` fueron rechazadas en las pruebas de ARMSX2 2.9.3.

Por tanto:

- Descargar a la caché o a Descargas no basta para instalar el estado.
- No se puede ofrecer preparación completamente automática en un móvil nuevo con el mecanismo actual.
- Sí puede plantearse KOTH condicionado a tener el estado instalado previamente y poder recargarlo por PINE.
- Una actualización del estado compartido exigiría repetir su instalación mientras no exista un puente compatible.

### 4.3 Conservar la preparación de slots de PC sin ajustes

PC usa su flujo de copia y carga con `--load-slot 9`. Android actualmente carga el índice PINE 0, correspondiente al slot 1 visible de ARMSX2.

No se deben intercambiar esos valores por el nombre del slot en la interfaz. La futura integración debe usar el slot realmente preparado en móvil y recargarlo en cada combate, incluso cuando el jugador conserva su posición.

### 4.4 Copiar la detección de redes de escritorio

`zerotier_networks.py` contiene consultas al servicio local, herramientas CLI y adaptadores de Windows/Linux. No constituye una integración con la app ZeroTier de Android.

La entrada manual de IPv4 ya ofrece una base. Descubrimiento automático, estado de la VPN y cambios de dirección requieren un mecanismo específico y pruebas en Android; no basta con copiar comandos de PC.

### 4.5 Habilitar espectadores con el paquete actual

La lista explícita de módulos de `mobile/prepare.py` incluye `hill.py`, pero **no incluye `spectator.py`**. El KOTH de PC depende de ese módulo tanto para observar como para transmitir.

El APK actual no está preparado para activar esas rutas tal cual. Además del empaquetado, faltan la integración del servicio, reproducción, transiciones de rol y evaluación del consumo.

## 5. Lo que todavía no puede garantizarse

- **Determinismo PC–Android:** que el estado se cargue y sus archivos coincidan no prueba que la simulación mantenga los mismos hashes durante una pelea completa.
- **Compatibilidad universal:** solo hay evidencia concreta sobre determinadas versiones y dispositivos. No cubre otros emuladores ni iOS.
- **Cola activa con pantalla apagada o procesos congelados:** el fabricante ya interrumpió procesos en las pruebas. La notificación por sí sola no lo resolvió en ese equipo.
- **Turnos automáticos sin fallos:** faltan pruebas de fin de sesión, recarga, cambio P2→P1 y conexión con varios rivales consecutivos.
- **Una experiencia fluida solo por mantener delay 3:** el valor ya existe, pero no elimina el RTT, las esperas ni las limitaciones de emulación observadas.
- **Acceso de red siempre disponible:** si el ganador pasa a host, debe recibir conexiones; no basta con que haya podido conectarse antes como cliente.
- **Recuperación transparente tras cortes:** `hill.py` detiene el flujo si acumula unos 12 segundos sin sincronización exitosa con Django. La congelación del servicio puede provocar problemas aunque la red del combate siga disponible.
- **Compatibilidad con el Django desplegado:** el repositorio permite analizar el contrato del cliente, pero aquí no se inspeccionó el código del backend ni su versión en producción.
- **Ganador automático:** no forma parte del método actual; requeriría un análisis adicional de detección y validación de resultados.

Estos puntos son incertidumbres o límites del sistema actual, no demostraciones de imposibilidad permanente.

## 6. Lo que no recomendaría trasladar

| Elemento | Motivo | Recomendación |
|---|---|---|
| Interfaz Tkinter completa | Diseñada para escritorio | Reutilizar datos y reglas; adaptar las pantallas existentes de Kivy |
| Un proceso Python de escritorio por pelea | No coincide con la ejecución móvil actual | Coordinar sesiones desde el servicio Android |
| Copia directa a carpetas privadas del emulador | El flujo probado no tiene acceso compatible | Preparación previa explícita hasta disponer de importación soportada |
| Experimentos rechazados de cambio de carpeta | No persistieron ni actualizaron la ruta efectiva | No recuperarlos como solución validada |
| Root, ADB o cambios globales del teléfono como requisito | No resuelven un flujo distribuible para el usuario común | Reservar ADB para diagnóstico; usar mecanismos compatibles con el emulador |
| Mantener Kivy visible para sostener la conexión | Compite con ARMSX2 y puede congelarlo al cambiar de app | Servicio, notificación y control flotante existente cuando sea necesario |
| Espectadores activados por defecto en la primera versión | Añaden emulación, conexiones, memoria y transiciones | Primera fase sin observar ni transmitir |
| Límites de espectadores de PC sin medir | El servidor admite hasta 64 MiB de historial y 16 espectadores, además de otros recursos | Medir en móvil antes de fijar límites o permitir transmitir |
| Observar siempre mientras se espera | Mantiene carga del emulador, temperatura y batería | Cola sin reproducción como opción inicial |
| Elegir siempre un PC como host | Cambia la regla actual de que el rey es P1 y limita móvil–móvil | Tratarlo como variante explícita si las pruebas lo justifican |
| Cambiar automáticamente a relay ante un fallo | Requiere coordinar a ambos jugadores y cumplir la autorización del servidor | Conservar un transporte acordado por combate |
| Quitar Discord para forzar entrada al relay | La validación documenta que el servidor rechazó al invitado | Respetar la autorización; distinguir relay de invitados KOTH por ZeroTier |
| Identificar al jugador solo por su nombre | No demuestra identidad ni recupera de forma segura la inscripción | Mantener credenciales y vinculación verificadas |
| Dar victorias por desconexión | Un móvil puede congelarse o perder conectividad | Mantener el resultado bajo control del organizador |
| Prometer “sin lag” o compatibilidad total | La evidencia actual no lo respalda | Comunicar condiciones y resultados medidos |

## 7. Alcance que recomendaría para una adaptación futura

Esta sección delimita una propuesta; no implica que se haya desarrollado.

1. **Participación básica:** consulta, inscripción o código, credencial persistente, cola y estado del turno. Separar estar inscrito de estar técnicamente listo para jugar.
2. **Preparación explícita:** estado ya instalado en slot 1 visible, juego/CRC correcto, símbolos compatibles y NetPad validado antes de anunciar disponibilidad.
3. **Coordinación desde el servicio:** sincronización con Django independiente de Kivy, estado visible y aviso de turno. Evitar dos sesiones simultáneas usando el mismo PINE.
4. **Combates por ZeroTier sin espectadores:** conservar protocolo, identidad por combate, delay publicado por el host y asignación de roles de Django.
5. **Rotación completa:** detener y liberar la partida anterior, recargar el estado, descartar tráfico anterior y admitir el siguiente rival. STOP debe interrumpir también preparación y espera.
6. **Recuperación controlada:** ante congelación, corte o fallo de PINE, mostrar que el jugador no está listo y permitir reintento sin duplicar inscripción ni asignar ganador.
7. **Espectadores después:** evaluar primero recepción opcional; habilitar transmisión móvil solo si consumo y estabilidad lo permiten.

El transporte relay ya aparece como alternativa en `hill.py`, pero no sustituye directamente a ZeroTier: requiere compatibilidad de Django, sala disponible y autorización del servidor principal. No sería la primera ruta que ampliaría para esta adaptación.

## 8. Pruebas necesarias antes de llamarlo KOTH funcional

| Prueba | Criterio de aceptación |
|---|---|
| Combate completo Android–Android | Resultado perfecto reportado por el usuario el 14/11/2026; queda documentar registros técnicos y estabilidad prolongada |
| Combate completo PC host–Android cliente | Resultado perfecto reportado por el usuario el 14/11/2026; queda documentar hashes de simulación |
| Combate completo Android host–PC cliente | Repetir con buena conexión del host móvil: la prueba reportada quedó trabada por mala conexión, según el usuario |
| Tres o más participantes | Ganador permanece, perdedor rota y siguiente rival conecta correctamente |
| Ganador que era P2 | Pasa a P1, recibe al nuevo P2 y no conserva recursos de la sesión anterior |
| Reinicio por combate | Cada pelea comienza desde el estado compartido, sin arrastrar memoria ni paquetes anteriores |
| Estado ausente, incorrecto o actualizado | No anunciar disponibilidad; explicar cómo preparar el emulador |
| Inscripción y reconexión | Conservan participante, puntos y posición sin duplicados |
| Cambio entre interfaz y emulador | Continúan presencia y transporte en los equipos probados |
| Cortes de Django, VPN y PINE | Estado coherente, reintento controlado y ninguna victoria automática |
| STOP durante espera, preparación y combate | Termina actividad y libera controles; informa si la liberación falla |
| Sesión prolongada con varias rotaciones | Sin acumulación de sockets/hilos, congelaciones ni degradación térmica inaceptable |
| Espectadores, si se incorporan | No bloquean a los jugadores; cambio de observador a jugador correcto y consumo medido |

No se ejecutaron pruebas durante la redacción. Los resultados funcionales del 14/11/2026 proceden del reporte del usuario; las pruebas de coordinación KOTH continúan pendientes.

## 9. Archivos usados como evidencia

- [README.md](../README.md): flujo KOTH de PC, reglas, ZeroTier y espectadores.
- [hill.py](../hill.py): sincronización con Django, disponibilidad, procesos, rotaciones y limpieza.
- [koth_client.py](../koth_client.py): eventos, inscripción, credenciales y vinculación Discord.
- [launcher.py](../launcher.py) y [launcher_koth.py](../launcher_koth.py): entrada al evento y tablero de escritorio.
- [netplay.py](../netplay.py): carga/copia de estados, sesiones y argumentos de KOTH.
- [spectator.py](../spectator.py): reproducción y límites del servidor de espectadores.
- [zerotier_networks.py](../zerotier_networks.py): descubrimiento de redes de escritorio.
- [mobile/main.py](../mobile/main.py): interfaz actual y consulta manual KOTH.
- [mobile/host.py](../mobile/host.py) y [mobile/host_service.py](../mobile/host_service.py): preparación del slot, ejecución P1/P2, servicio y liberación de controles.
- [mobile/prepare.py](../mobile/prepare.py): lista de módulos empaquetados.
- [mobile/README.md](../mobile/README.md) y [mobile/VALIDATION.md](../mobile/VALIDATION.md): condiciones de uso, pruebas físicas y experimentos rechazados.

**Dictamen:** adaptación técnicamente viable para Android con condiciones y respaldada por peleas completas exitosas reportadas en móvil–móvil y PC host–móvil cliente. Recomendada primero con estado previamente instalado, servicio propio de coordinación, ZeroTier y sin espectadores. Quedan repetir móvil host–PC cliente con buena conexión, documentar determinismo y validar la coordinación y rotación automática de KOTH.
