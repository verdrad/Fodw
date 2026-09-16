# Fodw v0.1

Bot de música para Discord, escrito en Python. Cola y reproductor independientes por servidor, slash commands, embeds y controles mediante botones. El dispositivo del oyente no importa: usa el cliente de Discord habitual.

## Estado y alcance

Implementado: búsqueda de YouTube, reproducción directa mediante FFmpeg, playlists de YouTube acotadas, búsqueda con selector y autocomplete, pausa, reanudación, saltos, seek real, barra visual de progreso, cola paginada, eliminar/mover/mezclar/limpiar, repetir, volumen persistente, historial de sesión y desconexión automática. Spotify admite metadatos de **canciones** y busca un equivalente en YouTube: la coincidencia es aproximada y el embed muestra la fuente realmente reproducida.

Pendiente: álbumes/playlists de Spotify, autoplay, lyrics, historial persistente opcional y recuperación de cola después de reiniciar. No hay un comando que simule implementar estas funciones.

La prueba real de audio necesita un bot de Discord configurado, FFmpeg, acceso a voz y contenido disponible. Las pruebas incluidas usan dobles de voz/proveedores; no certifican disponibilidad permanente de YouTube ni permisos de Spotify. No se incluye ningún token, cookie o base de datos real.

## Arquitectura elegida

```text
Discord (slash commands / botones)
    → MusicManager (sesiones y locks por guild)
        → GuildPlayer → Queue
        → TrackResolver
            → SpotifyProvider: sólo metadatos
            → AudioProvider / YouTubeProvider: búsqueda y URL reproducible
        → FFmpeg → Discord Voice (DAVE)
    → SettingsRepository (SQLite)
```

| Alternativa | Ventaja | Costo / decisión |
| --- | --- | --- |
| Python + discord.py + FFmpeg | Un proceso de control, SQLite incluido, lógica simple de probar | Un FFmpeg por guild que reproduce; extracción externa limitada a dos procesos |
| TypeScript + discord.js/voice | Ecosistema sólido, soporte DAVE | También necesita dependencias de voz/audio; no aporta una ventaja decisiva para este alcance |
| Bot + Lavalink | Audio desacoplado, útil para escalar y centralizar nodos | Servicio Java adicional y operación de nodos/plugins; pospuesto hasta medir carga real |

Decisión: Python 3.11+ (recomendado 3.12), discord.py 2.7.1 con extra `voice`, yt-dlp 2026.08.19 y FFmpeg. No se afirman consumos de RAM/CPU sin medirlos. La mayor carga será codificación de audio por guild; no se descargan canciones completas ni se actualiza el progreso con mensajes periódicos.

FlaviBot se investigó como referencia de UX y funciones públicas. No se encontró ni auditó un repositorio del núcleo que permita afirmar su arquitectura o reutilizar su código. Fodw es una implementación original; no se copió código de FlaviBot. Fuentes y versiones: [docs/research.md](docs/research.md).

## Ejecutar en Windows (PowerShell)

1. Instalá Python 3.12 desde [python.org](https://www.python.org/downloads/windows/), incluyendo el launcher `py`.
2. Instalá FFmpeg. Una opción es `winget install --id Gyan.FFmpeg -e`; también hay builds enlazados desde [FFmpeg](https://ffmpeg.org/download.html). Agregá su carpeta `bin` al PATH y abrí una terminal nueva.
3. Para el soporte actual de YouTube, instalá Deno desde [su documentación oficial](https://docs.deno.com/runtime/getting_started/installation/) y dejalo en PATH. yt-dlp usa su runtime JavaScript y el paquete `yt-dlp-ejs` incluido por el extra `default`. No se habilita descarga de componentes remotos ni se suministran cookies.
4. Dentro de la carpeta que contiene este README:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
ffmpeg -version
deno --version
.\.venv\Scripts\python.exe -m discord --version
```

5. Completá `.env` localmente. `DISCORD_TOKEN` es obligatorio. `DEV_GUILD_ID` es opcional y permite registrar comandos sólo en un servidor de prueba. Activá `YOUTUBE_ENABLED=true` para contenido y usos autorizados; esta integración depende del acceso y de las condiciones de la plataforma. No es una API oficial de audio de YouTube ni una garantía de reproducción.
6. Iniciá:

```powershell
.\.venv\Scripts\python.exe -m fodw
```

No es necesario activar el entorno virtual ni cambiar la política de ejecución de PowerShell. `FFMPEG_PATH` puede ser un ejecutable del PATH o una ruta absoluta propia; el proyecto no fija rutas de ninguna computadora. La configuración se valida al iniciar y explica si falta FFmpeg o el token.

## Configurar Discord

En el [Developer Portal](https://discord.com/developers/applications), creá una aplicación y su bot. Copiá el token sólo en `.env`. Instalalo en tu servidor con los scopes `bot` y `applications.commands`.

Permisos mínimos: Ver canales, Enviar mensajes, Insertar enlaces (embeds), Conectar y Hablar. No necesita Administrador, Message Content Intent ni Server Members Intent. Usa los intents de guild y estados de voz. Los canales de escenario no están soportados en esta versión.

Entrá en un canal de voz y ejecutá `/play query:Linkin Park Numb`. Los usuarios deben estar en el mismo canal que el bot para controlarlo. Cualquier participante de ese canal puede controlar la sesión; no hay un rol DJ en v0.1. Para moverlo entre canales usá `/leave` desde el actual y `/join` desde el nuevo. Si un moderador lo mueve, los controles verifican el nuevo canal del bot.

Los comandos globales pueden tardar en aparecer. Para desarrollo usá `DEV_GUILD_ID`. Al cambiar a comandos globales pueden quedar comandos de desarrollo registrados: eliminá los comandos de esa guild con la API de Discord o seguí usando el mismo modo de registro durante las pruebas.

## Comandos

| Comando | Función |
| --- | --- |
| `/join`, `/leave` | Entrar a tu canal / salir y borrar la cola |
| `/play query` | Texto, URL YouTube, playlist YouTube o canción Spotify |
| `/search query` | Hasta cinco resultados; selector personal durante 60 segundos |
| `/pause`, `/resume`, `/skip`, `/stop` | Pausa, reanuda, salta o detiene y vacía |
| `/seek position` | Salta realmente a `45`, `1:30` o `01:25`; también hay botones `⏪ -10s` y `⏩ +10s` |
| `/queue page` | Diez canciones por página; posiciones desde 1 |
| `/remove position` | Elimina una canción pendiente |
| `/move source destination` | Mueve dentro de las pendientes |
| `/clear`, `/shuffle` | Vacía pendientes / mezcla pendientes |
| `/loop mode` | `off`, `track`, `queue`; skip y fallos evitan repetir la actual |
| `/replay` | Encola otra vez la actual o la última del historial |
| `/nowplaying` | Embed con progreso consultado en ese momento y botones |
| `/volume value` | 0–100; persiste el valor por guild |
| `/history` | Hasta 25 canciones anteriores de la sesión |

Los botones duran 15 minutos y equivalen a los comandos. `/nowplaying` genera controles nuevos. El botón de loop recorre off → track → queue. El historial incluye canciones que terminaron, se saltaron o fallaron; no es un registro de escuchas completas.

El panel principal se actualiza cada 10 segundos para mostrar la barra de progreso sin generar ediciones continuas ni acercarse innecesariamente a los límites de Discord. `/nowplaying` fuerza una actualización inmediata. `/seek` reinicia el proceso FFmpeg con `-ss` antes de la entrada, por lo que el audio comienza realmente desde la posición indicada. La posición usa `time.monotonic()`, se pausa/reanuda sin contar el tiempo pausado y se acota entre 0 y la duración. Cada reinicio recibe un identificador: callbacks atrasados de FFmpeg quedan descartados y no avanzan la cola. Las transmisiones en vivo o de duración desconocida no admiten seek.

## Spotify y fuentes

Para canciones Spotify se necesita una aplicación en [Spotify for Developers](https://developer.spotify.com/dashboard) y sus `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`. Se usa Client Credentials para metadatos, sin inicio de sesión del oyente ni extracción de audio de Spotify. El acceso efectivo depende del modo, elegibilidad y restricciones de la aplicación. Fodw informa fallos de acceso y rate limits sin reintentar indefinidamente.

El proveedor devuelve título/artista a TrackResolver, que consulta el proveedor reproducible. La coincidencia puede ser una versión distinta; usá `/search` para elegir manualmente. Nuevas fuentes deben implementar `AudioProvider.resolve` y `AudioProvider.stream` y registrar explícitamente sus URLs permitidas. Las URLs arbitrarias, archivos locales y endpoints de red interna no se aceptan como fuentes.

## Estabilidad y recursos

- Hasta `MAX_QUEUE` canciones pendientes (100 por defecto, máximo configurable 500). Playlists grandes se truncan; entradas inválidas pueden omitirse. Una adición que excede el espacio restante se rechaza completa.
- Dos extracciones simultáneas como máximo, procesos cancelables, timeout de 40 segundos por extracción y timeout HTTP de Spotify de 15 segundos. Una búsqueda pendiente por guild y cooldown por usuario.
- El stream se resuelve al comenzar cada canción, evitando guardar URLs temporales en SQLite.
- Fallos de una canción notifican y avanzan. Errores al enviar el embed no cortan la música.
- discord.py maneja reconexión de voz. Tras 30 segundos desconectado se descarta la sesión; el usuario puede volver con `/play`. No se promete restauración exacta del progreso después de una caída.
- `EMPTY_TIMEOUT` (60 s): salir cuando no quedan oyentes humanos. `IDLE_TIMEOUT` (180 s): salir con cola vacía o pausa prolongada. Se evalúa cada cinco segundos.
- Al reiniciar o salir se pierde cola, loop e historial de sesión. SQLite conserva volumen; incluye campo de preferencias para un futuro autoplay, todavía inactivo.
- No registrar URLs firmadas, tokens ni respuestas crudas de proveedores. El diagnóstico registra tipos de error sin detalles sensibles. La carpeta `data/` está excluida de Git.

## Ubuntu / Linux

Instalá Python 3.11+ y FFmpeg desde los paquetes de tu distribución (Ubuntu 24.04 trae Python 3.12):

```bash
sudo apt update
sudo apt install python3 python3-venv ffmpeg libopus0
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
# Editar .env; instalar Deno siguiendo su documentación oficial.
.venv/bin/python -m fodw
```

Para ejecución continua, usá un servicio systemd con usuario sin privilegios, `WorkingDirectory` apuntando al proyecto y `ExecStart` al Python de `.venv`. No incluyas secretos en el archivo de unidad. Permití salida HTTPS y tráfico de voz de Discord; no hace falta publicar un puerto HTTP del bot. Corré una sola instancia por token en v0.1.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

La lógica de cola, almacenamiento y reproductor no importa Discord. `test_integration.py` valida offline la integración y serialización de comandos con la librería real, además del aislamiento entre metadatos y audio. No necesita credenciales.

Prueba manual antes de operar: dos guilds con colas distintas, pausa/reanudación, saltos en loop, falta de permisos de texto/voz, video no disponible seguido por uno válido, salir todos del canal, desconexión de red y reinicio. Verificá que cada guild conserva sólo su propio volumen y que un fallo no termina el proceso. Medí RAM/CPU con la cantidad prevista de guilds activas antes de decidir migrar a Lavalink.

## Problemas frecuentes

- **Falta FFmpeg:** verificá `ffmpeg -version` en la misma terminal; configurá `FFMPEG_PATH` si corresponde.
- **Voz/DAVE:** verificá `python -m discord --version` dentro del entorno. Reinstalá `discord.py[voice]==2.7.1` si faltan PyNaCl o davey; en Linux instalá libopus.
- **YouTube no disponible:** verificá Deno, versión de yt-dlp y disponibilidad del contenido. No agregues cookies privadas ni mecanismos para eludir restricciones. Actualizá dependencias de forma controlada y volvé a ejecutar pruebas.
- **Spotify 401/403/429:** revisá credenciales, acceso de la aplicación y límites; álbumes/playlists todavía no están implementados.
- **No aparecen slash commands:** revisá scopes de instalación y `DEV_GUILD_ID`; mirá si el proceso pudo sincronizar al iniciar.
