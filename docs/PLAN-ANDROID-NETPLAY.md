# Plan de adaptación de Netplay a Android

Este es el punto de partida para retomar la adaptación móvil. Cada bloque tiene una comprobación concreta. La [guía de referencias](REFERENCIAS-ANDROID-NETPLAY.md) indica dónde empezar y cómo registrar un fallo.

## Último avance

**Siguiente bloque: A1 · Slots de ARMSX2.** El análisis está terminado y queda por implementar la carga por variante. Hay evidencia de carga del slot 1. Los slots 2 y 3 están pendientes de prueba en un teléfono.

Trabaja un bloque por vez. Marca el bloque como terminado cuando pase su comprobación. Si ya está implementado y falta probarlo en un teléfono, deja la casilla abierta y anota **Implementado, pendiente de dispositivo**. Al cerrar una sesión, actualiza esta sección con el bloque, el resultado, el enlace a la evidencia y el siguiente paso.

## Base disponible en Android

- [x] PVP como P1 o P2 por Netplay público y por IP de ZeroTier.
- [x] Exportación de estados a Descargas y carga del slot 1 de ARMSX2.
- [x] Creación casual de Rey de la Colina con juego y estado.
- [x] Lista de torneos, inscripción, cuadro y conexión a cruces.
- [x] Acreditación de premios en Django. Los torneos casuales individuales entregan 20 puntos de tienda al primero y 15 al segundo. Los torneos oficiales individuales de Round Robin, Eliminación Simple y Eliminación Doble tienen premios configurables por puesto.

## Slots objetivo en Android

| Juego | Estado | Slot visible | Índice PINE |
|---|---|---:|---:|
| UN5 | Netplay original | 1 | 0 |
| UN6 | Netplay original | 1 | 0 |
| UN6 | Despertar | 2 | 1, por verificar |
| UN6 | Despertar con volumen al 20 % | 3 | 2, por verificar |

Netplay público usa el original. Las variantes de UN6 se ofrecen en ZeroTier y en eventos con esa configuración. La instalación de los archivos en ARMSX2 es manual en el flujo actual. La comprobación de memoria disponible distingue el original de Despertar, pero es igual en las dos variantes de Despertar. A1 incluye verificar cómo distinguirlas en una partida real. [Carga actual](../mobile/host.py#L139) · [Evidencia del slot 1](../mobile/VALIDATION.md#045--slot-1-exclusivamente-en-android)

## Bloques pendientes

- [ ] **A1 · Slots.** Resolver el slot por juego y variante en PVP, Rey de la Colina y Torneos. **Comprobación:** probar los tres slots en ARMSX2 y confirmar qué variante se cargó.
- [ ] **A2 · Descargas.** Exportar las variantes con nombres distintos e indicar su slot. En el flujo de Netplay público, exportar el original. **Comprobación:** verificar los archivos contra el catálogo e instalarlos por separado en el slot indicado.
- [ ] **A3 · Navegación.** Crear **Jugar** con PVP, Rey de la Colina y Torneos, **Juegos** con catálogo y descargas, **Ayuda** con configuración, guías y registros, e **Historial** con su acceso. **Comprobación:** cambiar de pantalla durante una sesión y conservar los controles para detenerla o volver a ARMSX2.
- [ ] **A4 · PVP.** Reunir P1 y P2, preseleccionar UN6 y ofrecer variantes al anfitrión de ZeroTier. El invitado usa el estado anunciado por el anfitrión. Conservar la conexión por IP y evaluar el descubrimiento de salas sobre la VPN por separado. **Comprobación:** jugar Android ↔ PC con el original por Netplay público y ambas variantes de Despertar por ZeroTier.
- [ ] **A5 · Rey de la Colina.** Separar Casual y Oficial, mostrar juego y variante, y preseleccionar UN6 al crear un casual. Los oficiales se crean en Django Tournament. Los eventos antiguos sin configuración conservan la selección manual. **Comprobación:** crear un casual y unirse a un oficial desde Android, comprobando el slot en ambos.
- [ ] **A6 · Torneos.** Separar Casual y Oficial. Permitir crear e iniciar casuales de Round Robin, Eliminación Simple y Eliminación Doble. Mostrar juego, estado y premios, y cargar lo que fija Django para el cruce. **Comprobación:** crear un evento de cada formato, completar un casual, verificar el abono de 20 y 15 una sola vez y comprobar los premios de un torneo oficial.
- [ ] **A7 · Historial y saldo.** Mostrar el historial de peleas con sesión de Discord, actualización y paginación. Mostrar el saldo confirmado por Django. **Comprobación:** probar historial vacío, cambio de página, sesión vencida y actualización tras un premio.
- [ ] **A8 · APK y prueba final.** Compilar e instalar la APK en un teléfono. **Comprobación:** verificar navegación, descargas, slots, conexión, reconexión y cierre de partida.

## Registro breve al retomar

Usa una línea por avance. Por ejemplo, `A1 [ ] · Slot 1 comprobado · Pendientes slots 2 y 3 · Evidencia en VALIDATION.md`. En la siguiente sesión basta con abrir este plan y continuar por el primer bloque pendiente.
