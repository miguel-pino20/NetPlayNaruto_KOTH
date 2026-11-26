# Referencias para adaptar y probar Netplay en Android

Empieza por el [plan y la lista de avance](PLAN-ANDROID-NETPLAY.md), y abre únicamente las referencias del bloque que vas a trabajar. La [guía móvil](../mobile/README.md) describe el flujo disponible en la APK y el [registro de validación](../mobile/VALIDATION.md) recoge lo probado en dispositivos.

| Bloque | Referencias |
|---|---|
| **A1 · Slots** | [Carga y validación en ARMSX2](../mobile/host.py#L139), [catálogo de estados UN6](../netlink.py#L29) y [prueba del slot 1](../mobile/VALIDATION.md#045--slot-1-exclusivamente-en-android). |
| **A2 · Descargas** | [Exportación móvil actual](../mobile/downloads.py#L96), [pruebas de exportación](../test_mobile_downloads.py) y [MediaStore en Android](https://developer.android.com/training/data-storage/shared/media). |
| **A3 · Menús** | [Guía básica de Kivy con ejercicios de interfaz](GUIA-KIVY-INTERFAZ-ANDROID.md), [navegación actual en Android](../mobile/main.py#L84) y [menús de PC](../launcher.py#L622). |
| **A4 · PVP** | [Argumentos de conexión móvil](../mobile/host.py#L79), [consulta del estado anunciado](../statesync.py#L121) y [ZeroTier para Android](https://docs.zerotier.com/android/). |
| **A5 · Rey de la Colina** | [Flujo móvil de inscripción](../mobile/main.py#L783), [servicio móvil de KOTH](../mobile/koth.py#L75) y [pruebas de KOTH móvil](../test_mobile_koth.py). |
| **A6 · Torneos** | [Lista y cuadro en Android](../mobile/main.py#L461), [panel de PC](../launcher_tournaments.py), [cliente de la API](../koth_client.py) y [pruebas de cruces móviles](../test_mobile_base.py). En el repositorio Django Tournament, `DJBase/urls.py` define las rutas y `home/score_reports.py` implementa la gestión de casuales y cruces. |
| **A7 · Historial y saldo** | [Historial de PC y llamada a la API](../launcher_account.py#L225). En Django Tournament, `home/discord_auth.py` calcula el saldo y `home/services.py` acredita los premios por puesto. |
| **A8 · APK** | [Compilar con el flujo del proyecto](../mobile/README.md#compilar-apk), [configuración de Buildozer](../mobile/buildozer.spec) y [guía oficial de ADB](https://developer.android.com/tools/adb). |

## Qué compartir si algo falla

- Bloque y paso exacto que estabas probando.
- Juego, variante y slot esperado, cuando corresponda.
- Resultado esperado y resultado observado.
- Mensaje de error exacto, captura o fragmento de registro sin credenciales.

Ejemplo breve: `A1 · UN6 Despertar · esperaba slot 2 · ARMSX2 cargó slot 1`. Para una prueba física, anota también las versiones de Android y ARMSX2 en el [registro de validación](../mobile/VALIDATION.md).
