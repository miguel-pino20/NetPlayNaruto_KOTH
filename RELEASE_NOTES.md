# UN5 Netplay 0.1.9A

## KOTH en Android

- La pestaña **KOTH** muestra los eventos disponibles en una lista. El evento seleccionado queda resaltado y se conserva al actualizar si sigue disponible.
- Inicia sesión con Discord para inscribirte o recuperar tu inscripción. KOTH usa la IPv4 de ZeroTier de la pestaña **Conexión** y te indica dónde corregirla si está vacía o es inválida.
- Tras conectar, pulsa **Volver a ARMSX2** y reanuda el mismo juego que seleccionaste en KOTH. El servicio usa el estado compartido ya instalado en el **slot 1** y muestra el rol asignado por Django: **En espera**, **P1**, **P2** o **Espectador**.
- La preparación de KOTH usa la misma comprobación de mandos virtuales que Host P1 y Cliente P2. Si el mando 2 está desconectado, lo activa como DualShock 2.

## KOTH en PC y Android

- La inscripción de Discord se conserva al pasar de un dispositivo a otro. Si cambia la IPv4 de ZeroTier registrada para ese evento, Django actualiza la dirección y descuenta **1 punto** cuando el jugador tiene saldo. El mínimo es **0** y volver a conectar con la misma IP conserva los puntos.
- El **código personal** sigue disponible en el launcher de PC. Se eliminó el vencimiento de 24 horas en Django. El código pierde vigencia al cerrar el evento o retirar al jugador. Un cambio de IP invalida la conexión anterior.
- El flujo de cambio de IP requiere el backend KOTH actualizado con la migración `0017_participant_netplay_address`.

## Cliente P2 en Android

- Selecciona la sala del servidor UN5 directamente en la lista. La sala elegida queda resaltada y el código se toma de esa selección.

## Descargas

| Plataforma | Paquete |
| --- | --- |
| Windows x64 | `UN5-Netplay-Windows-x64.exe` |
| Linux x86_64 | `UN5-Netplay-x86_64.AppImage` |
| Android ARM64 | `UN5-Netplay-Android-arm64-debug.apk` |

Cada paquete tiene su archivo `.sha256`. Android usa el código de versión `1026408`.

## Validación

- 113 pruebas automatizadas de UN5 Netplay correctas y comprobaciones internas de los paquetes de Windows y Linux superadas.
- SHA256 de los tres paquetes verificados. El APK conserva la firma de 0.1.8A.
- La inscripción en P5 desde el Infinix y el cambio a la IP de PC con puntaje cero se comprobaron durante el desarrollo. Queda validar un combate completo y la reproducción como espectador en Android.
