# D.O.N: salas y puentes ZeroTier

Cambios de código fuente para probar entre equipos, sin generar compilados.

## Actualización necesaria

1. Actualizar el proyecto Django y ejecutar `python manage.py migrate` con el entorno virtual del servidor activo. La migración nueva es `0015_don_short_codes_and_bridge`. Reiniciar el servicio Django.
2. Actualizar por Git el launcher de **todos** los jugadores y abrirlo desde el código fuente. En Windows se utiliza `1 - Run.bat`.
3. Crear una sala nueva: las salas existentes usan el protocolo anterior y no admiten mezclar launchers con y sin puentes.

Los perfiles de 2, 3 y 4 jugadores que ya se publicaron permanecen en Django; esta actualización no requiere volver a capturarlos ni subirlos.

## Crear y unirse

Con D.O.N abierto en PCSX2, seleccionar la IPv4 propia de ZeroTier. El host elige 2–4 jugadores y crea la sala. Los invitados introducen el código de **6 caracteres alfanuméricos**, la IPv4 ZeroTier del host, o `IP:puerto` si hay varias salas en la misma IP. Los UUID anteriores también pueden resolverse internamente.

La vista principal contiene crear/unirse, jugadores y rutas. La configuración de PCSX2 y publicación de estados está dentro de **Opciones de PCSX2 / administración**. Solo se necesita abrirla si la carpeta detectada, PINE o puerto UDP requieren ajustes.

`Estado listo` significa que el guardado ya se cargó. El inicio del host conecta el transporte UDP; el mensaje `Mandos conectados` indica que se completó el inicio del protocolo. Los errores de espera indican los puestos sin confirmación UDP o el estado de espera del juego.

## Estado persistente

El estado se guarda en la carpeta `sstates` seleccionada:

- `DON-inicial-Np-HASH.p2s`: estado inicial verificado por SHA-256.
- `DON-netplay/SYMBOLS_HASH.json`: símbolos verificados del adaptador.

Al volver a entrar, se reutilizan ambos archivos si coinciden con el perfil de Django. Si una instalación anterior ya guardó el estado pero no sus símbolos, se descarga solamente el JSON pequeño desde `/api/netplay/don/sessions/UUID/symbols/`. Un cambio del estado publicado requiere obtener su nueva versión.

PCSX2 sigue cargando mediante una ranura numerada temporal libre. Su limpieza tolera el bloqueo de archivos de Windows y se reintenta mientras la sesión continúa.

## Puentes

El protocolo `don-bridge-v1` mide RTT entre cada pareja y comparte esas mediciones por el mismo puerto UDP de la sala. Busca rutas sin bucles, con hasta cuatro equipos, usando la suma de los RTT de sus enlaces.

Por ejemplo, si P1↔P3 mide 120 ms y P1↔P2↔P3 suma 30 + 80 = 110 ms, puede utilizar P2 como puente. Los RTT mostrados para rutas indirectas son **estimaciones sumadas**, no una medición independiente de extremo a extremo. La ruta solo cambia si mejora más de 3 ms o 5 %, lo que sea mayor, y normalmente espera al menos 2 segundos entre cambios. Las mediciones expiran a los 10 segundos.

Los puestos y mandos P1–P4 permanecen fijos. P1 conserva la coordinación lógica de las entradas; los puentes reenvían los paquetes sin cambiar su origen. El protocolo conserva las confirmaciones y retransmisiones existentes. Una ruta enumera todos sus saltos, valida los equipos contra la sala y autentica sus paquetes dentro de la sesión. No se reenvía hacia direcciones ajenas a la sala.

La columna de rutas muestra las rutas estimadas desde el equipo local. Las entradas de invitados siguen pasando lógicamente por P1, aunque su recorrido físico use otro jugador como puente. Esto no garantiza que todo ping mejore: depende de los enlaces disponibles y del coste real de reenvío.

## Prueba manual pendiente

No se ejecutaron pruebas ni builds para este cambio. Para la comprobación entre equipos:

1. Crear una sala de 3 jugadores; entrar por código desde uno y por IP del host desde otro.
2. Iniciar y comprobar avance de fotogramas, mandos independientes y rutas visibles.
3. Salir y volver a entrar; comprobar el mensaje de reutilización del estado y que no se descargue el ZIP de nuevo.
4. Comprobar un caso donde un enlace indirecto sea mejor y observar el salto intermedio en la ruta estimada. Hacerlo solo con las herramientas de red que ustedes utilicen para la prueba.
5. Repetir con 2 y 4 jugadores. Si hay una espera, copiar el diagnóstico con puesto/IP o `hold`, máscara de mandos pendientes y fotograma.

D.O.N sigue siendo experimental: los hashes actuales comprueban entradas; la sincronía del estado de combate todavía no está certificada.
