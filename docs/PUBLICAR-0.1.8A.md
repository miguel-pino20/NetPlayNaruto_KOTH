# Publicar UN5 Netplay 0.1.8A

1. Abre https://github.com/miguel-pino20/NetPlayNaruto_KOTH/releases/new
2. Crea la etiqueta `v0.1.8A` y título `UN5 Netplay 0.1.8A`.
3. Adjunta los seis archivos de la carpeta `dist/` (tres aplicaciones y tres SHA256).
4. Puedes marcarla como prerelease. Publica la Release; subir archivos al código no basta.
5. Comparte el enlace de la Release en Discord.

Las tres aplicaciones comparten versión y repositorio. Las futuras publicaciones
necesitan un tag superior, por ejemplo v0.1.9A, y los mismos nombres de assets.
Android 0.4.x requiere instalar esta versión manualmente una vez. Desde 0.1.8A
muestra avisos de nuevas versiones; Android pide confirmar la instalación.
Conserva la misma clave de firma Android y aumenta ANDROID_VERSION_CODE.
KOTH en Android sigue incompleto. El estado de ARMSX2 sigue usando el slot 1.

Validado: 111 pruebas, builds PC con self-test, firma/alineación APK, arranque
Android y consulta real de GitHub. Falta la prueba completa de actualizar desde
una Release futura publicada hasta su instalación en Android.
Esta tarea no publicó nada en GitHub.
