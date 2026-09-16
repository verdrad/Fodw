# Validación de entrega

Fecha: 2026-09-15.

## Ejecutado

- Instalación real de discord.py 2.7.1 con PyNaCl 1.5.0 y davey 0.1.6, yt-dlp 2026.08.19 con EJS 0.8.0 y python-dotenv 1.2.3.
- Python 3.12 en Windows: **26 tests aprobados** con unittest.
- Registro y serialización de los 18 slash commands con la biblioteca real, sin login.
- Cola: aislamiento, límite atómico, posiciones, loop, skip, fallos e historial acotado.
- SQLite: volumen por guild, rango válido y persistencia al reabrir.
- Reproductor simulado: fallo seguido de canción válida, skip sin doble avance, stop/skip durante resolución, callbacks después de stop, error al notificar.
- Resolución: normalización de YouTube, rechazo de URLs ajenas y separación Spotify/audio.
- Cancelación de `/play` pendiente cuando una sesión se detiene o cierra.
- Construcción de FFmpeg con seek: `-ss` en `before_options`, sin `pipe`, `stdin` ni `stderr` entero.
- Barra y parsing de posiciones, además de seek durante pausa y callbacks viejos.

El runtime de Codex no pudo usar carpetas temporales creadas con permisos 0700. Para esta ejecución se usó un runner externo al proyecto que cambia únicamente la creación de esas carpetas temporales a 0777. No se alteró la lógica bajo prueba y ese runner no se distribuye con el bot. Las dependencias de prueba quedaron fuera de la entrega.

## No ejecutado

- Login, sincronización remota, botones reales y audio en Discord: no se proporcionó token.
- FFmpeg/Deno y reproducción real de YouTube: estos ejecutables no están instalados en este entorno.
- Spotify real: sin credenciales de aplicación.
- Pruebas reales de reconexión, permisos y varios servidores concurrentes.
- Ejecución en Ubuntu o benchmark de RAM/CPU. Se entrega workflow de CI Windows/Ubuntu; no se publicó ni ejecutó en GitHub.

Por lo tanto esta entrega es una v0.1 implementada y validada offline, pendiente de aceptación en un servidor de prueba antes de usarla de forma continua. Seguir la sección de prueba manual del README.
