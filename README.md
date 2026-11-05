# UN5 Netplay Launcher

Los compilados comprueban las releases de GitHub al abrirse y se actualizan
automáticamente si hay una versión posterior para su plataforma.
La versión y el repositorio se configuran en `release_info.py`.
Consulta [cómo publicar actualizaciones](UPDATES.md).

Para compilar Linux y Windows desde Linux con el Wine preparado del proyecto,
ejecuta `./build.sh`. También admite `./build.sh linux` y `./build.sh windows`.
Lee la versión de `release_info.py` y genera los paquetes y sus SHA256 en `dist/`.

## Windows: un solo ejecutable

El paquete `dist/UN5-Netplay-Windows-x64.exe` incluye el launcher, Python y sus
dependencias. Abre únicamente netplay; el jugador inicia PCSX2 por separado.
No requiere Python instalado ni los `.bat`/`.sh` del proyecto.
Para construirlo con Python de Windows x64: `py windows/build_windows.py`.
Consulta [las instrucciones de Windows](windows/README.md).

## Linux: un solo AppImage

El paquete `dist/UN5-Netplay-x86_64.AppImage` incluye el launcher y sus dependencias.
Al abrirlo también ejecuta PCSX2, que debe estar instalado mediante Flatpak
(`net.pcsx2.PCSX2`). No incluye el emulador, BIOS ni juegos.
Para construirlo: `python3 appimage/build_appimage.py`.
Consulta [las instrucciones de AppImage](appimage/README.md) para distribuirlo y usarlo.

## Partida de dos jugadores por ZeroTier

Pulsa **ZeroTier · 2 players**. Ambos PCs deben estar autorizados en la misma
red ZeroTier y tener PCSX2 abierto con el juego y PINE habilitado.

1. P1 elige **HOST**, selecciona su red (`Nombre — IPv4`) y pulsa **START ZEROTIER**.
2. P1 comparte la IPv4 seleccionada con P2; el host escucha en UDP 47400.
3. P2 elige **GUEST**, selecciona su propia red e introduce la IPv4 de P1 en
   **Host's ZeroTier IPv4**. Después pulsa **START ZEROTIER**.

El launcher comprueba y descarga el estado y los símbolos del servidor habitual
antes de iniciar. La pelea conecta directamente por ZeroTier con delay 3;
no necesita un torneo, código KOTH ni sala del servidor principal. Permite UDP
47400 en el firewall del host. La conexión se enlaza a la IP local seleccionada.
Estas partidas no aparecen en la lista de salas online. **STOP** termina la sesión.

## Rey de la colina con Django y ZeroTier

Django coordina los turnos. Las peleas de KOTH conectan directamente por ZeroTier,
con 3 frames de delay. Los participantes en espera también pueden observar por
ZeroTier en su propio PCSX2. HOST/GUEST fuera de KOTH conserva el servidor principal.

La URL pública de Django es `https://narutimateonline.sytes.net`.
El launcher corrige automáticamente el dominio anterior mal escrito
(`narultimateonline.sytes.net`) en las configuraciones guardadas.

1. En Django, instala la actualización y ejecuta `python manage.py migrate`.
2. Todos deben estar autorizados en la misma red ZeroTier. El host debe permitir
   UDP 47400 para jugar y TCP 47401 si habilita espectadores.
   Cada PC debe tener PCSX2 con PINE habilitado,
   el juego abierto y los mismos archivos de save state y symbols de UN5 o UN6.
   El launcher comprueba y descarga el estado y los símbolos del servidor de
   archivos habitual por HTTP antes de entrar. Los controles del combate viajan por ZeroTier.
3. En **Your Role** selecciona **KOTH**. El panel de salas cambia a una lista de
   eventos de Django. La URL del sitio se puede editar encima de la lista.
   Selecciona el evento y pulsa **JOIN KOTH** (también puedes hacer doble clic).
4. Confirma tu nombre y selecciona tu red de ZeroTier; la IPv4 es obligatoria.
   Si tienes la sesión de Discord del launcher activa,
   Django la verifica con el servidor principal y vincula la inscripción a tu
   misma cuenta de Discord. Sin esa sesión, te inscribe como invitado. Se guarda
   una credencial local por sitio y evento para reconocer la inscripción al
   volver; una reconexión no crea otro participante ni reinicia los puntos.
   Si ya estás inscrito desde la web, puedes usar el botón inferior
   **King of the Hill · personal code**, con tu código obtenido en la página del
   torneo mediante **Conectar netplay con ZeroTier**. Las dos formas de entrada
   muestran el mismo tablero en vivo: partida actual, siguiente jugador, cola,
   puntos y meta del evento. El código manual también permite vincular una
   inscripción de invitado a tu Discord verificado, conservando puntos y posición.
   Abre la web con la misma cuenta Discord para que aparezca como tu participante.
   No se identifica a una cuenta únicamente por su nombre visible.
   El desplegable ZeroTier muestra `Nombre de red — IPv4`.
   **Refresh networks** vuelve a consultar las redes. Si Linux exige permisos,
   **Read network names…** solicita autorización solo para leer los nombres y
   los guarda para próximas aperturas; no hace falta ejecutar el launcher como
   administrador. También puedes escribir la IP. **Enable spectators** permite
   desactivar la transmisión y la observación sin salir de la cola.
   En Windows se consulta primero el servicio local de ZeroTier para obtener
   los nombres reales de las redes, usando la copia de autenticación del usuario
   que proporciona su instalador. Esa clave se utiliza solo en localhost y no
   se guarda ni se envía a Django. Si no se puede consultar el servicio, se
   buscan los adaptadores ZeroTier y sus IPv4 mediante PowerShell. Mantén
   ZeroTier abierto y pulsa **Refresh networks** después de conectar una red.
   Al entrar se comprueban los archivos y se carga el estado en PCSX2, congelado
   hasta tu turno. STOP libera el juego y desconecta, sin borrar la inscripción.
5. El organizador inicia el torneo desde Django. Cuando los dos jugadores del
   turno estén conectados y sus archivos coincidan, el launcher recarga el estado
   en el slot 9. El primero en la cola es P1/host; Django entrega su IP de ZeroTier
   al rival/P2. La pareja conecta directamente, sin crear una sala en el relay.
   Cada sesión tiene una identidad propia para rechazar paquetes de peleas anteriores.
6. Después del combate, **el organizador registra el ganador en el panel de
   Django**. El launcher cierra la sesión anterior, el ganador sigue primero y
   el perdedor pasa al final. La siguiente pareja arranca automáticamente.

**STOP** desconecta del netplay; no retira tu inscripción del torneo. Para salir
de la cola usa la página del torneo. Si falla un combate, vuelve a entrar a este
modo para reintentar el mismo turno; no se asignan victorias por desconexión.
Cada combate comienza desde el save state compartido. Si el ganador antes era
P2, pasa a P1 en la siguiente sesión.

**Espectadores:** cuando la pareja está lista, los demás inscritos con el mismo
juego, estado y símbolos reciben una transmisión de controles de solo lectura
desde uno de los dos jugadores. Cada jugador habilitado sirve una copia del
historial en su TCP `port+1`. El espectador compara en paralelo el tiempo de
conexión y autenticación a ambas fuentes y conserva la más rápida disponible.
La medición aproxima la latencia desde el espectador; no usa el ping entre jugadores.
Sus mandos no se envían y sus conexiones no participan en las esperas
ni en la comparación de hashes de los jugadores. La cola sigue mostrándose en
la consola; al llegar tu turno, el launcher cierra la reproducción, recarga el
estado y te conecta como jugador.

La reproducción comienza desde el inicio del combate: si entras tarde, lo ves
con retraso, sin saltar al instante actual. Una transmisión interrumpida no te
retira de la cola: tras 5 segundos se recarga el estado y se vuelven a comparar
las fuentes, reproduciendo otra vez desde el comienzo. Cada jugador que transmite
conserva hasta 64 MiB de historial y atiende hasta 16 espectadores; si se agota
el búfer, desactiva la transmisión y los jugadores continúan. No se retransmite
video ni se consulta PINE desde los hilos que atienden espectadores. Elegir una
fuente más rápida no garantiza que la emulación local muestre la misma imagen:
PCSX2, el juego, el estado, los símbolos y la configuración deben ser compatibles.
Las transmisiones consumen ancho de banda y recursos del PC aunque no bloqueen
el protocolo de la pelea.

Para las dos fuentes actualiza también `home/netplay.py` de Django y reinicia
el servicio. Este cambio no requiere una migración adicional a la 0011.

Hay que actualizar el launcher en **todos los PCs**, `home/netplay.py`,
`home/models.py` y la migración `0011_koth_transport_spectators.py` en Django.
Ejecuta `python manage.py migrate`. Con `--port N`, la transmisión
usa TCP `N+1`. La API pública desplegada debe reiniciarse después de actualizarla.

También se puede ejecutar desde terminal, definiendo `UN5_HILL_TICKET` en el entorno:

```bash
python netplay.py --symbols /ruta/symbols.json hill \
  --api-url http://127.0.0.1:8000 --address 10.147.0.12 --game un6 \
  --state /ruta/match.p2s --state-dir /ruta/PCSX2/sstates --load-slot 9
```

El launcher y KOTH usan **3 frames** de input delay. Ambos jugadores siguen el
valor publicado por el host. Desde terminal puedes indicar `--delay 0` para
calcularlo por el ping, o elegir 2–10 frames manualmente.
Desde terminal, `--transport relay` permite usar el servidor principal si ambos
jugadores lo eligen; `--relay-server` y `--relay-api-url` configuran ese servidor.
El valor predeterminado es `--transport zerotier`. `--api-url` es la URL de Django.
`--no-spectators` permite comparar el comportamiento sin transmisión de espectadores.
`--port` permite cambiar el puerto del host (47400 por defecto).
Las pruebas automatizadas no sustituyen una prueba real con dos PCs y PCSX2.

For PCSX2 installed with Flatpak, close PCSX2 and start it using
`bash "2 - PCSX2 Flatpak.sh"` before opening the launcher. This puts the PINE
socket in Flatpak's shared application runtime directory, so the Linux launcher
can connect from outside the sandbox. Enable PINE (slot 28011) and start the game.
While using the local Linux fixes, launch with
`UN5_SKIP_UPDATE=1 bash "1 - Run.sh"` to avoid overwriting them with upstream files.

**Language / Idioma:** [English](#-english) · [Português (BR)](#-português-br)

---

## 🇺🇸 English

Desktop launcher (Python/Tkinter) for **UN5 Netplay**, a 2-player lockstep online mode for *Naruto Shippuden: Ultimate Ninja 5* running on PCSX2. It wraps the existing `netplay.py` as a subprocess: it does not replace or reimplement the network logic.

### Features

- **Discord login:** your name and avatar show up in the room list and in the game.
- **Room list** with host and guest avatars, match phase (`SELECTING` / `IN FIGHT`), real ping, and match time.
- **Fixed input delay:** the launcher uses 3 frames; the guest uses the room's value.
- **Match state sync:** the default save state and `symbols.json` are downloaded from the server when yours differ.
- **Owner-only PREPARE:** the room owner prepares the match state, which is then published to the server automatically.
- **Extra tools:** load the match state into PCSX2, solo test, PINE test, and release game.

### Requirements

- Windows with Python 3.10+ (Tkinter is included in the standard Windows distribution).
- The **original Naruto Shippuden: Ultimate Ninja 5 game ISO**. A modified or patched ISO is not required by the netplay launcher.
- The **latest available version of PCSX2**, with **PINE enabled** (default slot `28011`).
- [Pillow](https://pypi.org/project/Pillow/) (optional, install with `pip install pillow`): without it, the room list has no avatars.
- The netplay project files in the same folder as `launcher.py`: `netplay.py`, `core_link.py`, `node.py`, `netlink.py`, `statesync.py`, `pine.py`, `selftest_netpad.py`, `rooms.py`, `wire.py`, `lockstep.py`, `simgame.py`.
- The online server (relay / accounts) is **not included** in this repository. The address the launcher connects to is `SERVER_ADDR` in `launcher_core.py`.

### How to run

Run from a terminal:

```bash
python launcher.py
```

Or double-click `1 - Run.bat`.

User data (preferences, Discord session, and match state) is stored in `%APPDATA%\UN5 Netplay`.

### How to play

**Host**

1. Log in with Discord (top right).
2. Choose **HOST · P1** and click **START HOST**.
3. The launcher downloads the match state from the server, loads it into PCSX2 (frozen at frame 0), and opens your room.

**Guest**

1. Log in with Discord.
2. Click an open room in the **ROOMS** list.
3. Click **CONNECT AS GUEST**.

### Notes

- Loading the match state **overwrites PCSX2 save slot 9**. Use a slot you do not care about losing.
- Both players need pad 2 connected in PCSX2.
- Only one PINE client can run at a time. Close other PINE tools during a session.
- **STOP** asks the session to end cleanly so the real pads are restored. If the game stays frozen, use **Tools → RELEASE GAME**.
- Both PCs must have byte-identical match states; the launcher handles this by downloading the server's copy.
- Match state files (`.p2s`) and `symbols.json` are not part of the repository.

---

## 🇧🇷 Português (BR)

Launcher desktop (Python/Tkinter) do **UN5 Netplay**, um modo online lockstep para 2 jogadores de *Naruto Shippuden: Ultimate Ninja 5* rodando no PCSX2. Ele executa o `netplay.py` existente como subprocesso: não substitui nem reimplementa a lógica de rede.

### Recursos

- **Login com Discord:** seu nome e avatar aparecem na lista de salas e dentro do jogo.
- **Lista de salas** com avatar do host e do guest, fase da partida (`SELECTING` / `IN FIGHT`), ping real e tempo de partida.
- **Input delay fixo:** o launcher usa 3 frames; o guest usa o valor definido pelo host.
- **Sincronização do estado da partida:** o save state padrão e o `symbols.json` são baixados do servidor quando os arquivos locais são diferentes.
- **PREPARE exclusivo do dono:** o dono da sala prepara o estado da partida, que é publicado automaticamente no servidor.
- **Ferramentas extras:** carregar o estado da partida no PCSX2, teste solo, teste do PINE e liberar o jogo.

### Requisitos

- Windows com Python 3.10+ (o Tkinter já vem na distribuição padrão do Python para Windows).
- A **ISO original de Naruto Shippuden: Ultimate Ninja 5**. O launcher de netplay não exige uma ISO modificada ou com patches.
- A **versão mais recente disponível do PCSX2**, com o **PINE habilitado** (slot padrão `28011`).
- [Pillow](https://pypi.org/project/Pillow/) (opcional, instale com `pip install pillow`): sem ele, a lista de salas fica sem avatares.
- Os arquivos do projeto de netplay na mesma pasta do `launcher.py`: `netplay.py`, `core_link.py`, `node.py`, `netlink.py`, `statesync.py`, `pine.py`, `selftest_netpad.py`, `rooms.py`, `wire.py`, `lockstep.py`, `simgame.py`.
- O servidor online (relay / contas) **não está incluído** neste repositório. O endereço usado pelo launcher é `SERVER_ADDR` em `launcher_core.py`.

### Como abrir

Execute pelo terminal:

```bash
python launcher.py
```

Ou dê dois cliques em `1 - Run.bat`.

Os dados do usuário (preferências, sessão do Discord e estado da partida) ficam em `%APPDATA%\UN5 Netplay`.

### Como jogar

**Host**

1. Faça login com o Discord (canto superior direito).
2. Escolha **HOST · P1** e clique em **START HOST**.
3. O launcher baixa o estado da partida do servidor, carrega-o no PCSX2 (congelado no frame 0) e abre sua sala.

**Guest**

1. Faça login com o Discord.
2. Clique em uma sala aberta na lista **ROOMS**.
3. Clique em **CONNECT AS GUEST**.

### Observações

- Carregar o estado da partida **sobrescreve o slot 9 de save do PCSX2**. Use um slot cujo conteúdo você não se importe de perder.
- Os dois jogadores precisam do controle 2 conectado no PCSX2.
- Apenas um cliente PINE pode funcionar por vez. Feche outras ferramentas que usem PINE durante a sessão.
- **STOP** pede para a sessão encerrar de forma limpa e devolver os controles reais. Se o jogo continuar congelado, use **Tools → RELEASE GAME**.
- Os dois PCs precisam ter estados de partida idênticos, byte a byte. O launcher cuida disso baixando a cópia do servidor.
- Os arquivos de estado da partida (`.p2s`) e o `symbols.json` não fazem parte do repositório.

### Vinculación Discord entre el launcher y la web

Conecta Discord en el launcher, actualiza Django y vuelve a entrar al evento.
Django consulta el endpoint de confianza del servidor principal y utiliza su ID
de Discord para recuperar la misma cuenta que usa el navegador. Una inscripción
anterior de invitado se vincula solo si conservas su clave local o código
personal. Se mantienen los puntos, el puesto en la cola y el historial.

Para actualizar el Django publicado copia `home/netplay.py`,
`home/netplay_identity.py`, `DJBase/settings.py` y `DJBase/urls.py`, y reinicia
el servicio. No hay migraciones nuevas. El endpoint de identidad predeterminado
es `https://un5netplay.duckdns.org/accounts/me`; el administrador puede cambiarlo
con `NETPLAY_IDENTITY_URL` si cambia el servidor principal. La sesión del
servidor principal solo se envía en una cabecera HTTPS para comprobar la cuenta;
Django no la guarda. Si falla la comprobación, no se crea una inscripción de
invitado de forma silenciosa.
