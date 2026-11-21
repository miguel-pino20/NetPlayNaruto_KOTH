# Marcador automático · Guía para el servidor Django

Para quien mantiene `https://narutimateonline.servegame.com/`.

**Resumen:** djTourney recibe resultados automáticos de la pareja KOTH o de P1 de un cruce en
`POST /api/netplay/result/`. Un resultado válido se aplica sin confirmación:
suma un punto y avanza la cola de Rey de la Colina o actualiza el cuadro de
Round Robin, eliminación simple o eliminación doble. Un empate se registra
sin sumar puntos ni cerrar el cruce.

El contrato está implementado en Django. El marcador y su envío desde Netplay
siguen en desarrollo y no forman parte de la versión publicada. Las pruebas
de Django simulan el reporte de P1 con solicitudes de prueba.
---

## 1. JSON previsto para el marcador de Netplay

El marcador en desarrollo usa PINE para detectar quién gana cada pelea y los
personajes de ambos lados. Estas son las salidas previstas para el JSON.

| Salida | Dónde | Para qué |
| --- | --- | --- |
| Archivo | `placar.json` y `placar.txt` en la carpeta de datos del launcher (`%APPDATA%\UN5 Netplay\` en Windows) | OBS u otro programa en la misma PC |
| API local | `GET http://127.0.0.1:47500/score` | Overlays en la misma PC |
| WebSocket | `ws://127.0.0.1:47500/ws` (envía el marcador al conectar y en cada cambio) | Overlays en vivo |
| Envío a Django | `POST` a la ruta que tú crees | **El sitio** (requiere conectar el envío del launcher) |

El archivo está activado por defecto; la API local y el WebSocket se activan en
`scoreboard.json` (`outputs.http.enabled`). Las tres primeras son locales (`127.0.0.1`):
el servidor **no puede leerlas**. Por eso
el envío al sitio tiene que ser un `POST` desde el launcher hacia Django.

Ejemplo real de `placar.json` / `GET /score`:

```json
{
  "p1": 2,
  "p2": 0,
  "draws": 0,
  "total": 2,
  "names": {"p1": "LUCARIO DRAGO", "p2": "Indiana"},
  "text": "LUCARIO DRAGO: 2 | Indiana: 0",
  "updated": 1795218978.07,
  "last": {
    "winner": "p1",
    "ts": 1795218978.07,
    "source": "memoria",
    "n": 2,
    "chars": {
      "p1": {"id": 106, "code": "kar", "name": "Karin"},
      "p2": {"id": 92, "code": "sai", "name": "Sai"}
    }
  }
}
```

## 2. Qué cuenta y qué no

- Cuenta cuando el juego llega a su **pantalla de resultado**. Gana quien queda con vida;
  si se acaba el tiempo, gana quien tiene más vida.
- **No cuenta:** salir por el menú, cargar un save state ni el empate por tiempo. En UN6
  el empate por tiempo y la salida por el menú hacen el mismo recorrido en el juego y no
  se pueden distinguir. El empate no da puntos y las reglas de KOTH ya prevén revancha.
- Validado en UN6 (`SLUS-55606`, CRC `688C83D6`) el 20/11/2026: KO de P1, KO de P2,
  victoria por tiempo, personaje del mod (Karin) y salida por el menú.
- En salas casuales de Netplay o ZeroTier, P1 registra la sala y comparte con P2
  una invitación privada y el número de pelea. Cada cliente usa su propia sesión
  de Discord para enviar a `POST /api/netplay/casual/result/`. P2 adjunta la
  invitación en `X-Casual-Guest`. Ambos usan la clave `<session>-<match_number>`.
  El primer resultado válido recibe HTTP 201. Un segundo reporte del mismo ganador
  recibe HTTP 200 con el mismo ID. Si difieren, Django conserva el primero y devuelve HTTP 409.
- En KOTH, los dos jugadores reportan la victoria con sus respectivos códigos. Django guarda el primer ganador de la ronda y rota la cola una sola vez. En los cruces programados envía P1.

## 3. Contrato de Django

Por cada pelea terminada, el launcher puede enviar:

```http
POST /api/netplay/result/
Authorization: Bearer <token>
Idempotency-Key: 3f1c9a0b2d4e5f60718293a4
Content-Type: application/json
```

```json
{
  "event": "result",
  "winner": "p1",
  "source": "memoria",
  "score": {"p1": 2, "p2": 0, "draws": 0},
  "names": {"p1": "LUCARIO DRAGO", "p2": "Indiana"},
  "characters": {
    "p1": {"id": 106, "code": "kar", "name": "Karin"},
    "p2": {"id": 92, "code": "sai", "name": "Sai"}
  },
  "match_number": 2,
  "session": "<round_id o session_epoch de la pareja>",
  "idempotency_key": "3f1c9a0b2d4e5f60718293a4",
  "timestamp": 1795218978.07
}
```

| Campo | Significado |
| --- | --- |
| `winner` | `p1`, `p2` o `draw`. P1 = host, P2 = guest de esa pelea. |
| `score` | Marcador acumulado en el launcher (no el de Django). |
| `names` | Nick de cada jugador en el netplay. |
| `characters` | ID del personaje, código del modelo y nombre mostrado en el juego. |
| `match_number` | Número de la pelea dentro de la sesión del launcher. |
| `session` | El `round_id` / `session_epoch` que ya devuelve `/api/netplay/sync/`. |
| `idempotency_key` | Igual a la cabecera. Si llega repetido, guardar **una sola vez**. |

Django verifica que la credencial pertenezca a un jugador de la pareja KOTH o a P1 del cruce programado y
resuelve al ganador con los IDs de sus inscripciones. Los nombres, personajes,
contadores y la fecha enviados por el launcher se guardan como metadatos. El
marcador acumulado local no se suma al torneo: cada victoria válida vale un punto.

## 4. Autenticación y prueba

- **Rey de la Colina oficial o casual.** Cada jugador usa su código personal de KOTH.
  Envía en `session` el `round_id` o `session_epoch` obtenido de `/api/netplay/sync/`.
  Django verifica que la pareja sigue activa. El proceso principal debería enviar
  el resultado para mantener el código personal fuera del proceso de la pelea.
- **Round Robin, eliminación simple y eliminación doble.** El launcher puede
  consultar sus cruces listos con `GET /api/netplay/fixtures/`, usando
  `X-Netplay-Session`. El P1 vinculado a Discord solicita su credencial con
  `POST /api/netplay/events/<event_id>/fixtures/<fixture_id>/result-ticket/`
  usando la misma cabecera. La respuesta incluye `ticket`, `session`, `p1_id`
  y `p2_id`. El ticket autoriza un solo cruce y vence en 12 horas.
- **Respuestas.** `201` para un reporte nuevo y `200` con `duplicate: true`
  al repetir la solicitud con el mismo contenido y clave. El cuerpo devuelve
  `status` (`recorded` o `draw`), `session`, `match_id`, `winner_id`
  y `winner_points`. Los tres últimos son nulos en caso de empate. Un
  `400` indica datos inválidos, `403` indica credencial o rol inválido y
  `409` indica sesión cerrada, cruce indisponible o conflicto de idempotencia.

Para probarlo localmente, aplica `python manage.py migrate` en una base de
pruebas. En un evento activo, usa la credencial del host y el identificador de
sesión emitido por ese Django. Este ejemplo aplica un resultado al evento usado
en la prueba, así que ejecútalo con un torneo de prueba.

```bash
curl --fail-with-body http://127.0.0.1:8000/api/netplay/result/ \
  -H "Authorization: Bearer ${RESULT_TICKET}" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: prueba-resultado-1' \
  --data "{\"event\":\"result\",\"winner\":\"p1\",\"source\":\"memoria\",\"match_number\":1,\"session\":\"${RESULT_SESSION}\",\"idempotency_key\":\"prueba-resultado-1\"}"
```

En djTourney, `python manage.py test home.test_score_reports` crea eventos
aislados con credenciales de prueba y verifica los cuatro formatos.

## 5. Requisitos para que sea 100 % automático

Django aplica automáticamente el resultado recibido. El envío desde el launcher y
la validación en una partida real quedan pendientes.

### De tu lado (Django)

- [x] **Ruta creada** que acepte el `POST` de la sección 3 (o la que elijas, avisándonos).
- [x] **Credencial validada**: código personal KOTH o ticket del cruce.
- [x] **Jugador verificado:** Django comprueba la pertenencia a la pareja en KOTH y el rol P1 en cruces programados.
- [x] **Ronda identificada:** `/api/netplay/sync/` devuelve el identificador de la ronda
      (`round_id` / `session_epoch`) y la ruta lo acepta en `session`.
- [x] **Duplicados ignorados** por `Idempotency-Key`.
- [x] **El punto se aplica solo:** Django rota la cola o actualiza el cuadro sin
      confirmación del organizador.
- [ ] **Evento de prueba** y un `curl` de ejemplo con token de prueba, para validar
      juntos antes de un torneo real.

### Pendiente en el launcher

- [ ] **Activado por defecto en KOTH:** el marcador y el envío se encienden solos en las
      peleas de KOTH, con la URL del sitio ya puesta. Hoy hay que editar `scoreboard.json`
      a mano.
- [ ] **Token entregado al envío:** en KOTH el proceso principal ya tiene el código; en los demás formatos P1 solicita el ticket de su cruce.
- [ ] **Ronda correcta en el envío:** usar el identificador de ronda que devuelve
      `/api/netplay/sync/`.
- [ ] **Prueba de punta a punta** en tu evento de prueba: KO, victoria por tiempo y salida
      por el menú (que no debe llegar al sitio).

### Juegos cubiertos

- [x] UN6 (`SLUS-55606`, CRC `688C83D6`): validado.
- [x] Accel 2 JP (`SLPS-25837`): detecta P1/P2; empate sin probar.
- [ ] Mod de Matheus: falta su perfil (sección 6). **Hasta tenerlo, sus peleas no se
      envían solas.**

### Lo que seguirá siendo manual

- **Empate por tiempo** en UN6: el juego no lo distingue de salir por el menú, así que no
  se envía. Como no da puntos y la regla es revancha, no afecta al marcador del torneo.
- **Faltas, abandonos y retiradas** de `REGLAS-Y-PRUEBAS-KOTH.md`: el marcador solo
  detecta quién gana la pelea. Esas reglas siguen en manos de Django y del organizador.

## 6. Mod de Matheus

Su mod usa el mismo serial (`SLUS-55606`) con otra estructura de memoria, así que
necesita su propio perfil. Necesitamos:

1. El **CRC** de su build (aparece en el log de PCSX2, o con `python pine.py` con el juego
   abierto).
2. Que juegue unas peleas con `python scoreboard.py watch` abierto y nos diga el
   resultado de cada una, en orden: una victoria de P1 por KO, una de P2 por KO y una
   salida por el menú.

## 7. Probarlo sin servidor

Con PCSX2 y el juego abiertos y PINE activado:

```bash
python scoreboard.py init     # crea scoreboard.json (desactivado por defecto)
python scoreboard.py watch    # muestra el marcador y cada resultado en vivo
```

Cada pelea terminada imprime una línea como:

```
Placar: J1: 2 | J2: 0  - vencedor: P1 (Karin vs Sai)
```

Y el `placar.json` se actualiza con el JSON de la sección 1.
