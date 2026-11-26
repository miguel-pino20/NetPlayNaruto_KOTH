# Naruto Netplay Android · Python/Kivy

Versión 0.1.8A (compartida con Windows y Linux). Reutiliza el protocolo y el núcleo Python de PC. No incluye D.O.N,
Digimon, BIOS, juegos, estados empaquetados ni credenciales.

Para continuar la adaptación, consulta el [plan y la lista de avance](../docs/PLAN-ANDROID-NETPLAY.md)
y la [guía de referencias por bloque](../docs/REFERENCIAS-ANDROID-NETPLAY.md).
Para practicar la interfaz y el menú, empieza por la [guía básica de Kivy](../docs/GUIA-KIVY-INTERFAZ-ANDROID.md).

## Descargar un estado para pasarlo manualmente a ARMSX2

En **Conexión**, seleccionar UN5 o UN6 bajo **Estado compartido para ARMSX2** y
pulsar **Descargar estado en Descargas**. La app descarga y verifica el estado,
reutiliza la copia válida y guarda el archivo en:

- `Descargas/NarutoNetplay/UN5-Netplay.p2s`
- `Descargas/NarutoNetplay/UN6-Netplay.p2s`

No requiere PINE, emulador abierto, Discord, USB ni permiso de acceso general al
almacenamiento. Usa MediaStore en Android 10 o posterior. El usuario se encarga
de importar/copiar ese archivo a ARMSX2; el botón no modifica su configuración.
El flujo de conexión sigue esperando el estado preparado en el slot 1.

## Preparación y conexión (P1 o P2)

1. Activar PINE en ARMSX2, puerto 28011, y abrir UN5 o UN6.
2. El estado compartido debe estar previamente instalado en el **slot 1 visible**
   (índice PINE 0). En el Infinix de pruebas se instaló por USB. La descarga a la
   carpeta privada de Netplay no lo instala en ARMSX2.
3. Host P1 crea la partida; Cliente P2 selecciona Directo/ZeroTier e introduce
   la IP del host, o Servidor UN5 y elige una sala del listado. El servidor
   principal exige autorización de Discord para entrar como cliente.
4. La app descarga y verifica estado y símbolos privados si faltan o cambiaron.
   Si ya existe una copia válida, la reutiliza. Abre ARMSX2 y pide Reanudar.
5. Prepara los puertos virtuales como DualShock2 si estaban desconectados,
   carga el slot 1 y valida la firma NetPad antes de conectar.
6. Para ZeroTier, ambos dispositivos deben estar autorizados en la misma red.
   El cliente introduce la IP ZeroTier del host. El relay principal usa sus salas.

**Instalación automática pendiente:** las propuestas 0.4.1/0.4.2 fueron rechazadas
al probar ARMSX2 2.9.3. Descargar y exportar funciona, pero PINE no permite
transferir un estado al almacenamiento privado del emulador. Cambiar la carpeta
por SetSetting tampoco funciona: el cambio no se guarda al reiniciar y
ApplySettings no recarga EmuFolders. La instalación probada tampoco mostró las
funciones de importación del código fuente más reciente. No distribuir esos
APKs experimentales; se retiraron de dist y de mobile/bin. Falta un puente de
transferencia de estados compatible con el emulador. No se cambió su APK.
KOTH aún está pendiente de integración de partidas en Android.

**Detener partida** pide finalizar de forma limpia. Volver enseguida a ARMSX2
permite liberar los controles si el fabricante lo había congelado. La liberación
se reintenta durante 30 segundos. Si no se logra, el estado del servicio lo indica:
recargar un estado o reiniciar el juego para recuperar los mandos. No cerrar la
app desde recientes durante una sesión: el servicio no se reinicia automáticamente.

## Batería y segundo plano

El servicio está separado de la interfaz Kivy; esta deja de sondear su estado
cuando está pausada. La notificación usa un canal visible de baja prioridad.
El control flotante es una vista nativa de 128 × 30 dp, inicialmente arriba y
centrada, con transparencia. No ocupa ni captura los toques del resto de la
pantalla y no toma el foco de ARMSX2. Arrastrar para mover; mantener un segundo
y soltar para detener la partida. La posición se conserva. No necesita mantener
una ventana Kivy renderizando ni un bloqueo de CPU permanente.

En el Infinix de pruebas, el control visible evitó la congelación del servicio
que persistía incluso con notificación y excepción de batería. Esta prueba no
garantiza persistencia en todas las marcas ni durante sesiones prolongadas.
En dispositivos que congelan procesos, revisar **Ajustes → Apps → Naruto Netplay
→ Batería → Permitir uso en segundo plano → Sin restricciones**. No se debe
suponer que un servicio en primer plano basta para todos los fabricantes.
Consultar `VALIDATION.md` para los resultados reales y límites de las pruebas.

## Otras funciones

- Diagnóstico PINE de solo lectura: estado, ID, CRC y versión; distingue timeout
  al conectar TCP de timeout esperando respuesta a un comando.
- Configuración privada del puerto, IP local y URL KOTH.
- Introduce tu IPv4 fija de ZeroTier en **Conexión**. En **KOTH**, actualiza la
  lista y selecciona un evento. Con una sesión Discord verificada puedes inscribirte o recuperar
  tu inscripción sin duplicarla. Si la IP registrada para ese evento cambia,
  Django descuenta un punto hasta un mínimo de cero. Selecciona el mismo juego
  que abriste en ARMSX2. Tras conectar, vuelve al emulador y pulsa Reanudar.
  El servicio comprueba el estado ya instalado en el slot 1 y muestra el rol
  asignado por Django: En espera, P1, P2 o Espectador.
- Flujo Discord existente mediante `DiscordMixin`, navegador externo y sesión
  privada. La interfaz no descarga avatares. El secreto OAuth permanece en servidor.

## Ejecutar la interfaz en Linux

```bash
uv venv --python 3.12 mobile/.venv
uv pip install --python mobile/.venv/bin/python -r mobile/requirements.txt
mobile/.venv/bin/python mobile/main.py
```

La interfaz usa datos separados del launcher de PC. Los servicios P1/P2 requieren
Android; en Linux se sigue usando el launcher de escritorio.

## Compilar APK

Requiere JDK compatible, compilador C/C++, make, autoconf, automake, libtool,
cmake, pkg-config, git, zip/unzip y dependencias. La primera compilación descarga
SDK/NDK y requiere varios GB. En este equipo las herramientas faltantes se
prepararon localmente en `.toolchain/`; esa carpeta no se versiona.

```bash
uv pip install --python mobile/.venv/bin/python buildozer 'Cython<3' pip setuptools wheel
./mobile/build_apk.sh
```

`prepare.py` copia una lista explícita de módulos compartidos a `build/app/`.
No copia el repositorio entero ni datos personales. El APK debug queda en `bin/`;
las entregas verificadas se copian a `../dist/`. Android mínimo 8/API 26, ARM64,
target API 35. `buildozer.spec` permite aceptar las licencias SDK.

Los permisos nuevos corresponden al servicio de conexión y su notificación:
FOREGROUND_SERVICE, FOREGROUND_SERVICE_CONNECTED_DEVICE, CHANGE_NETWORK_STATE
(que satisface el requisito del tipo connectedDevice) y POST_NOTIFICATIONS.
El código no cambia las redes del usuario. INTERNET permite PINE y el transporte
con el rival. El manifiesto permite encontrar las variantes previstas de ARMSX2
para abrirlas, sin pedir visibilidad de todas las aplicaciones.
SYSTEM_ALERT_WINDOW se usa exclusivamente para el control flotante opcional;
requiere autorización especial de Android. No se solicita WAKE_LOCK.

## Pruebas y trabajo pendiente

```bash
mobile/.venv/bin/python -m unittest test_mobile_base test_pine test_koth_client test_zerotier_networks
```

Pendiente: importación general de estados al emulador, validación física de mandos y rotaciones KOTH,
prueba completa con P2 real y comparación de hashes,
espectadores y medición prolongada de RAM, CPU, batería y FPS. No confundir una
prueba de diagnóstico o handshake con una pelea validada. Ver `VALIDATION.md` y
`../ANDROID_PLAN.md`.


## Actualizaciones

Al abrir consulta las Releases públicas del repositorio configurado en
`release_info.py`. Una versión posterior muestra un aviso para descargar el APK;
Conexión también permite Buscar, Descargar e Instalar. Requiere APK y SHA256
publicados con los nombres de ASSET_NAMES. La instalación solicita confirmación
de Android y conserva los datos si el APK es compatible y mantiene la firma.
Consulta [UPDATES.md](../UPDATES.md) antes de publicar.
