# Marcador automático · Guía para el servidor Django

Para quien mantiene `https://narutimateonline.servegame.com/`.

**Resumen:** sí, el launcher ya genera un JSON con el resultado de cada pelea. Ese JSON
queda en la PC del jugador. Para que llegue al sitio, falta **una ruta en Django que lo
reciba**. Esa es tu parte. Abajo está qué hacer y qué enviarnos, y en la sección 5 la
lista completa de lo que falta para que el envío sea **100 % automático**.

---

## 1. El JSON que ya genera el launcher

El launcher lee la memoria del juego (PINE) y detecta solo quién gana cada pelea, con el
personaje de cada lado. Publica el marcador de cuatro formas. Todas usan el mismo JSON.

| Salida | Dónde | Para qué |
| --- | --- | --- |
| Archivo | `placar.json` y `placar.txt` en la carpeta de datos del launcher (`%APPDATA%\UN5 Netplay\` en Windows) | OBS u otro programa en la misma PC |
| API local | `GET http://127.0.0.1:47500/score` | Overlays en la misma PC |
| WebSocket | `ws://127.0.0.1:47500/ws` (envía el marcador al conectar y en cada cambio) | Overlays en vivo |
| Envío a Django | `POST` a la ruta que tú crees | **El sitio** (falta tu parte) |

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
- Solo el **host (P1)** envía al sitio, para que cada resultado llegue una sola vez.

## 3. Tu parte en Django

Crear **una ruta que reciba un `POST` con JSON** por cada pelea terminada.
Propuesta: `POST /api/netplay/result/`. El launcher enviará esto:

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

Lo que la ruta tiene que hacer:

1. **Validar el token** (ver la pregunta 2 abajo) y comprobar que ese jugador es el host
   de esa ronda.
2. **Ignorar duplicados** por `Idempotency-Key`. Si falla la red, el launcher reintenta
   hasta 3 veces.
3. **Guardar el resultado.** Recomendamos empezar con el resultado **pendiente de
   confirmación del organizador**, y pasar a sumar el punto y rotar la cola
   automáticamente cuando esté probado en torneo.
4. **Responder:** `200` o `201` si se guardó, `200` también si era un duplicado, y un
   `4xx` con un mensaje claro si la ronda ya cerró o no es de ese jugador. Los `4xx` no
   se reintentan (salvo `429`).

## 4. Qué enviarnos

Responde estas preguntas (puede ser en este mismo archivo):

1. **Ruta:** ¿sirve `/api/netplay/result/`? Si no, ¿cuál?
2. **Token:** ¿qué usa el host para autenticarse?
   - A) el mismo código KOTH personal que ya usa `/api/netplay/sync/`, o
   - B) un token propio solo para resultados.

   Hoy el launcher **no pasa** el código KOTH al proceso de la pelea, a propósito. Con la
   opción A, el envío lo haría el proceso principal de KOTH. Cualquiera de las dos nos sirve.
3. **Ronda:** ¿con qué campo identifica Django la pelea (`round_id`, `session_epoch` u
   otro)? ¿En el JSON o en la URL?
4. **Jugadores:** ¿Django ya sabe quién es P1 y P2 en cada ronda, o necesita otro dato
   (ID de inscripción, ID de Discord)? Hoy solo enviamos el nick.
5. **Puntos:** ¿automático o pendiente de confirmación? ¿Qué hacer con un `draw` (doble KO)?
6. **Respuestas:** el código y el cuerpo de éxito, duplicado y error.
7. **Campos:** ¿quieres todos los campos del JSON de arriba, o sobran o faltan algunos?
8. **Pruebas:** una URL o un evento de prueba, y un `curl` de ejemplo que funcione con un
   **token de prueba**. No envíes tokens reales por chat.

Con eso conectamos el launcher a tu ruta y probamos juntos en el evento de prueba.

## 5. Requisitos para que sea 100 % automático

Hoy el envío al sitio **todavía no es automático**: la parte del launcher está lista, pero
falta lo siguiente. Cuando todo esté marcado, cada pelea de KOTH llegará sola al sitio,
sin que nadie toque nada.

### De tu lado (Django)

- [ ] **Ruta creada** que acepte el `POST` de la sección 3 (o la que elijas, avisándonos).
- [ ] **Token definido** (opción A o B de la pregunta 2) y validado en la ruta.
- [ ] **El host queda verificado:** la ruta comprueba que quien envía es el host de esa ronda.
- [ ] **Ronda identificada:** `/api/netplay/sync/` devuelve el identificador de la ronda
      (`round_id` / `session_epoch`) y la ruta lo acepta en `session`.
- [ ] **Duplicados ignorados** por `Idempotency-Key`.
- [ ] **El punto se aplica solo:** la ruta suma el punto y rota la cola sin esperar al
      organizador. Mientras se prueba puede quedar pendiente de confirmación, pero
      **para ser 100 % automático este paso tiene que ser automático**.
- [ ] **Evento de prueba** y un `curl` de ejemplo con token de prueba, para validar
      juntos antes de un torneo real.

### De nuestro lado (launcher), en cuanto respondas

- [ ] **Activado por defecto en KOTH:** el marcador y el envío se encienden solos en las
      peleas de KOTH, con la URL del sitio ya puesta. Hoy hay que editar `scoreboard.json`
      a mano.
- [ ] **Token entregado al envío:** según tu elección, el envío lo hace el proceso
      principal de KOTH (que ya tiene el código) o usa el token nuevo.
- [ ] **Ronda correcta en el envío:** usar el identificador de ronda que devuelve
      `/api/netplay/sync/`.
- [ ] **Prueba de punta a punta** en tu evento de prueba: KO, victoria por tiempo y salida
      por el menú (que no debe llegar al sitio).

### Juegos cubiertos

- [x] UN6 (`SLUS-55606`, CRC `688C83D6`): validado.
- [x] Accel 2 JP original (`SLPS-25837`, CRC `C0659AD1`): detecta P1/P2; empate sin probar.
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
