# KOTH en PC y Android · Reglas y pruebas pendientes

Acuerdos del 19 de noviembre de 2026. Esta nota describe el comportamiento
propuesto y las pruebas realizadas. El prototipo de captura quedó archivado.
El organizador sigue registrando manualmente las victorias y los puntos en
Django.

## Salir o abandonar

Al pulsar **Detener**, pedir confirmación en el launcher de PC y en Android,
incluido el control flotante cuando esté disponible.

- **Seguir en KOTH** cierra el aviso y conserva la conexión.
- **Salir y conservar mi lugar** desconecta al jugador y lo marca como no
  disponible. Conserva la inscripción, los puntos y el lugar en la cola en ese
  momento. Si ya estaba peleando, esta salida cuenta como una falta. El aviso
  muestra el contador y advierte si la salida confirmada será la tercera.
- **Abandonar el evento** retira al jugador de la cola. Si había un combate
  activo, el rival gana inmediatamente y recibe el punto. Si el jugador estaba
  en espera o como espectador, el abandono no otorga una victoria. Si el evento
  sigue abierto y hay cupo, el jugador puede volver a inscribirse al final de la
  cola con **0 puntos**.

## Faltas durante un combate activo

- Cada jugador acumula sus propias faltas por enfrentamiento. Las primeras dos
  permiten reintentar con la misma pareja. El primero que llega a **3 faltas**
  pierde y Django aplica la rotación normal de KOTH.
- Una desconexión o desincronización solo cuenta cuando se puede identificar
  quién salió primero. Detectar primero un desync o recibir un timeout no
  demuestra quién salió. Un incidente ambiguo queda sin falta atribuida.
- Si ambos clientes reportan el mismo incidente, Django lo cuenta una vez.
  El contador se reinicia al finalizar el enfrentamiento. La victoria y, si
  corresponde, la retirada deben persistir juntas y una sola vez.

## Disponibilidad y selección de personaje

- Desde que Django asigna una pareja, cada jugador tiene **25 segundos** para
  estar disponible, tener el emulador preparado y conectar con su rival. Si el
  fallo de disponibilidad, respuesta del emulador o conexión se puede atribuir
  a un jugador, se le retira de la cola.
- En la selección de personaje, cada jugador tiene **25 segundos desde que el
  menú acepta sus controles** para realizar una acción reconocida, como mover
  el cursor, cambiar de personaje o confirmar. Quien ya confirmó se considera
  listo. Si la inactividad es atribuible, se retira al jugador de la cola.
- Una congelación o un fallo compartido que impida identificar al responsable
  queda sin retirada automática. El reingreso tras una retirada es al final de
  la cola con **0 puntos**, con el evento abierto y cupo disponible.
- Falta acordar si el rival gana un punto por una retirada de 25 segundos
  **antes de que empiece el combate**, o si espera al siguiente jugador.

## Prioridad de validación: victorias

- Primero validar una señal que distinga la victoria final de P1 y P2. En P8 se
  observó a Asuma ganar como P1 (PC), a Jugo ganar como P2 (Android) y a Asuma
  ganar como P2 (PC), con Android como P1 en esta última prueba.
- La pantalla mostró al vencedor y, en las pruebas de confirmación, el ganador
  pudo avanzar con X mientras el otro jugador no pudo. El registro actual pasó
  a `idle=1` tanto con victoria de P1 como con victoria de P2, así que ese
  indicador por sí solo no identifica al ganador.
- La próxima prueba debe registrar la fase y la acción de NetPad desde antes
  del golpe final hasta la pantalla de victoria, antes de pulsar X. Mantener el
  registro de puntos en manos del organizador.
- La validación del empate se pospone hasta confirmar las victorias. Se
  conserva la regla de repetir con la misma pareja cuando se confirme un empate.

## Empate

Si el juego confirma un empate como resultado final del combate, KOTH genera
otra pelea entre los mismos jugadores, sin sumar puntos ni rotar la cola.
Un empate de una ronda interna se interpreta según las reglas del juego.

Según lo observado por el usuario en UN6, un empate devuelve a ambos jugadores
directamente al menú de selección de personaje. En las victorias probadas en
P8, el juego mostró al vencedor y el ganador pudo confirmar con X para avanzar.
La siguiente prueba debe registrar la secuencia completa en ambos dispositivos.
El regreso a selección por sí solo también puede ocurrir después de una victoria
confirmada o un reinicio, por lo que no basta para identificar un empate.

## Pruebas por dispositivo

| Prueba | PC | Android |
| --- | --- | --- |
| Resultado UN6 | Jugar como P1 y P2. Guardar el registro de NetPad y una captura del resultado final. | Hacer las mismas pruebas con los roles invertidos y guardar el registro y la pantalla de ARMSX2. |
| Salir y abandonar | Probar las tres opciones durante el combate y desde espera o espectador. | Repetir desde la pestaña KOTH y el control flotante, cuando esté disponible. |
| Faltas | Provocar tres salidas atribuibles, luego salidas alternadas y un desync sin responsable identificable. | Repetir con Android como quien sale y comprobar el mismo contador y resultado desde ambos equipos. |
| Plazo de 25 segundos | Probar falta de disponibilidad, fallo de conexión y ausencia de acción en selección. | Repetir los casos y verificar que confirmar personaje cuenta como listo. |
| Cola y reingreso | Verificar en Django que se conserva el lugar al salir y que el abandono o retirada permiten volver con cero puntos al final. | Verificar la misma cola y puntuación desde Android. |

Para identificar victoria o empate, empezar con KO de P1, KO de P2, fin de
tiempo con ventaja y doble KO o vida igual al agotarse el tiempo. Comparar
pantalla final y telemetría de ambos equipos, separando el resultado de una
ronda del resultado del combate. Para el empate, grabar desde los últimos
segundos de pelea hasta el regreso a selección. Verificar luego que KOTH genere
otra pelea con la misma pareja, los mismos puntos y la misma cola.

Durante estas pruebas, registrar resultados observados sin automatizar todavía
el puntaje ni la rotación a partir de NetPad.
