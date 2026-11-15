# Naruto Netplay para Android: alcance y validación pendiente

Fecha: 2026-11-14.

## Estado y autorización

Este documento conserva las indicaciones del usuario para retomar el trabajo en el futuro.
El usuario autorizó después crear y ejecutar una base, usando Python para
reutilizar el proyecto, generar un APK y apagar la PC al finalizar.
La base está en `mobile/`; consultar `mobile/README.md` para conocer su alcance.
Todavía no se ha probado una partida PC ↔ Android. Sí se ha validado PINE en
un Infinix X6855 con Android 16 y ARMSX2 2.9.3; ver `mobile/VALIDATION.md`.
Al retomar, leer este archivo y seguir las nuevas indicaciones del usuario.

## Objetivo

Adaptar la lógica de Naruto del proyecto a una aplicación Android que se conecte
por PINE al ARMSX2 del mismo dispositivo y permita jugar con usuarios de PCSX2 en
Windows y Linux mediante ZeroTier, conservando KOTH y el login con Discord.

## Alcance solicitado

- Naruto: lógica de controles, preparación de partida y sincronización.
- KOTH: eventos, inscripción, cola, turnos, puntos y cambio automático de rival
  según la coordinación del servidor Django.
- ZeroTier: conexión entre Windows, Linux y Android.
- Login con Discord: incluirlo en Android y conservar la vinculación de la
  identidad verificada con la inscripción KOTH. No identificar cuentas solo
  por su nombre visible. Revisar el flujo actual antes de definir su adaptación.
- Aplicación móvil lo más liviana posible y preparada para permanecer activa
  mientras ARMSX2 está en pantalla.

Excluir D.O.N y Digimon Rumble Arena 2, sus interfaces y funciones específicas.
Conservar las utilidades compartidas que Naruto necesite.
La inclusión de espectadores en Android queda por definir; no asumir que deben
estar activos por defecto.

### Avance: host móvil P1 experimental (0.2.0)

El usuario autorizó crear partidas como jugador 1 y un control flotante que no
moleste a los botones táctiles. Se añadió un servicio Android y la pestaña Host P1,
reutilizando `netplay.py`, `core_link.py`, `node.py` y `wire.py` sin reescribir el
protocolo. El control es pequeño, movible y no enfoca su ventana; requiere mantener
un segundo y soltar para parar. Puede desactivarse desde la interfaz.

En el teléfono real se cargó el estado UN6 publicado de PC y se validó NetPad.
Desde Fedora se recibieron HELLO/DATA del miembro 1, slot 0, y se verificaron los
servidores de estado/símbolos. No se confirmó una pelea con P2 real ni determinismo.
La importación general de estados, los turnos KOTH y la prueba por ZeroTier siguen
pendientes; este host es directo y no aparece como sala del relay.

## Arquitectura observada

- `pine.py`: cliente PINE. Actualmente usa TCP local en Windows y sockets Unix
  en Linux; se debe contemplar el transporte Android explícitamente.
- `core_link.py`: acceso a NetPad, controles, hashes y datos de sincronización
  mediante memoria del juego.
- `node.py`, `wire.py`, `netplay.py`: intercambio de entradas, coordinación de
  frames, preparación/carga del estado y detección de divergencias.
- `hill.py`, `koth_client.py`, `launcher_koth.py`: coordinación KOTH con Django
  y presentación en el launcher.
- `zerotier_networks.py`: detección de redes dependiente del escritorio; no
  trasladarla a Android sin revisar sus diferencias.
- `discord_auth.py`, `launcher_account.py`: puntos de partida para revisar el
  login y la identidad existentes.
- El launcher actual usa Python/Tkinter y subprocesos. La interfaz y el ciclo de
  vida requieren una adaptación Android; no basta con empaquetar el escritorio.

PINE conecta cada aplicación con su emulador local. ZeroTier transporta los
controles entre dispositivos. Django organiza KOTH.

El estado preparado contiene código modificado de Naruto en memoria, incluido
el hook NetPad. Abrir la ISO original y activar PINE no basta para este protocolo.

## Viabilidad y riesgos sin resolver

La arquitectura parece viable, pero la compatibilidad real sigue sin certificar.

1. El código público de ARMSX2 consultado en el análisis incluye PINE por TCP
   en loopback para Android y operaciones de memoria y guardado/carga por slot.
   Verificarlo en la versión exacta de la APK elegida; no asumir que cualquier
   versión instalada se comporta igual.
2. Comprobar si ARMSX2 carga el mismo `.p2s` utilizado por PCSX2, conserva el
   hook, los símbolos y el estado congelado en frame 0.
3. Comprobar determinismo entre PCSX2 y ARMSX2: las mismas entradas deben generar
   resultados compatibles. El origen común de los emuladores no lo garantiza.
4. Resolver acceso/importación de estados en Android. El código actual copia
   archivos directamente a la carpeta de estados del emulador; el almacenamiento
   privado de Android puede impedir ese procedimiento entre aplicaciones.
5. ZeroTier existe en Android, pero su integración y detección de redes difieren
   del escritorio. Una IP manual es una opción para la primera validación.
6. Revisar el flujo de Discord y su contrato con el servidor antes de adaptar
   autenticación, persistencia de sesión y vinculación KOTH.

## Consumo y continuidad en segundo plano

### Pausa al cambiar de aplicación: hallazgo posterior a la primera APK

El usuario observó que ARMSX2 se pausa al abrir la aplicación acompañante.
El código público consultado de `MainActivityRuntime.kt`, en `onPause()`, abre
`InGameOverlay` cuando la VM está ejecutándose; el propio código indica que eso
pausa la VM. No asumir que existe una opción para desactivarlo en la APK del usuario.

Separar dos comprobaciones: PINE puede responder con estado `paused` aunque el
juego no avance. El diagnóstico actual muestra ese estado, pero eso no certifica
que NetPad pueda capturar nuevos frames. Si no responde PINE, investigar ese fallo
por separado: la pausa no demuestra por sí sola que el servidor PINE esté apagado.

El flujo de partida debe dejar ARMSX2 visible y ejecutar la conexión en un servicio
de la app acompañante. Un servicio en primer plano ayuda a mantener esa conexión,
pero no obliga a ARMSX2 a reanudar ni elimina su pausa al perder el foco. Probar
el regreso al emulador, pulsar Reanudar y completar allí la conexión sin exigir
volver a la interfaz del launcher. No depender de un temporizador en la interfaz
Kivy para hacer trabajo mientras está pausada. La primera APK no implementa este
servicio ni puede resolver todavía ese flujo.

Referencia del hallazgo:
https://github.com/ARMSX2/ARMSX2/blob/master/platforms/android/app/src/main/java/com/armsx2/runtime/MainActivityRuntime.kt

Requisito del usuario: minimizar RAM, CPU y batería de la app acompañante para
reducir su impacto en ARMSX2 y el riesgo de cierre en segundo plano.

Orientaciones técnicas propuestas, pendientes de validar:

- Interfaz sencilla, sin animaciones ni recursos pesados innecesarios.
- Durante la partida mantener solo las tareas necesarias: PINE, red y KOTH.
- Evitar esperas activas, consultas redundantes y registros sin límite.
- Acotar buffers e historial, especialmente si se incluyen espectadores.
- Evaluar un servicio en primer plano con notificación persistente y los
  requisitos de la versión Android objetivo.
- Mantener el login Discord sin consultas continuas innecesarias.
- Medir el consumo junto con ARMSX2, no solo el de la app aislada.

Una app liviana y un servicio en primer plano no garantizan que Android nunca
termine el proceso. Validar restricciones de batería del fabricante, presión
de memoria y recuperación de desconexiones en dispositivos reales.

## Orden propuesto de pruebas

1. Registrar dispositivo, versión Android, APK/versión ARMSX2, versión PCSX2,
   juego/región/CRC, estado, símbolos y configuración relevante.
2. Verificar PINE: conexión local, identificación del juego, lecturas y
   escrituras controladas, reconexión y cierre limpio.
3. Verificar estado y hook: carga del estado compartido, firma `g_np_report`,
   estructura NetPad, captura de controles y congelación/liberación del juego.
4. Comparar entradas reproducibles y hashes entre PC y Android durante selección,
   combate, jutsus, QTE y cambios de escena. Comparar también comportamiento visible;
   un hash parcial coincidente no certifica por sí solo toda la simulación.
5. Probar ZeroTier con PC como host y Android como invitado, después al revés;
   medir latencia, pérdida, pausas y estabilidad en Windows y Linux.
6. Validar login Discord, recuperación de sesión y vinculación con KOTH sin
   duplicar participantes ni perder puntos o posición al reconectar.
7. Validar cola KOTH, cambios de rival, recarga del estado, cambio de P2 a P1,
   desconexiones y salida limpia. El flujo actual registra el ganador desde
   el panel del organizador; no asumir detección automática del ganador.
8. Hacer sesiones prolongadas con ARMSX2 en pantalla: medir RAM, CPU, batería,
   temperatura, rendimiento del juego y continuidad del proceso acompañante.
9. Si se incluyen espectadores, evaluar su compatibilidad y consumo por separado.

Primero demostrar PINE + estado + sincronía PC/Android. Después ampliar a la
aplicación completa. Si falla el estado o el determinismo, investigar el bloqueo
antes de invertir en la interfaz; podrían requerirse cambios en el hook o emulador.

## Referencias para revisar al retomar

- ARMSX2 PINE: https://github.com/ARMSX2/ARMSX2/blob/master/pcsx2/PINE.cpp
- Plataformas ZeroTier: https://docs.zerotier.com/compatibility/
- Almacenamiento Android: https://developer.android.com/training/data-storage
- Documentación local: `README.md` y los módulos citados anteriormente.

Las fuentes externas y APIs pueden cambiar. Volver a verificar las versiones y
restricciones aplicables cuando se autorice empezar el trabajo.
