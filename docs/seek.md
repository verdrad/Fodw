# Seek y panel de reproducción

`GuildPlayer` conserva la fuente de verdad de posición en `PlaybackPosition` (`fodw/position.py`). El reloj monotónico calcula los segundos transcurridos; `pause()` congela el cálculo y `resume()` ajusta el ancla. El panel de Discord sólo representa ese estado.

Al ejecutar `/seek 1:30` o pulsar `⏪`/`⏩`, `GuildPlayer.seek()` valida la duración y prepara primero un nuevo `FFmpegPCMAudio`. Si la creación falla, el audio anterior sigue intacto. Después invalida el `playback_id` anterior, detiene su fuente y arranca la nueva con `-ss 90` en `before_options`, sin `pipe` ni `stdin` y sin pasar `subprocess.DEVNULL` como `stderr`. En discord.py 2.7, `stderr` debe ser un archivo; el sentinel entero `DEVNULL` se interpreta como un pipe y provoca el error `int has no attribute write`. Si estaba pausado, la nueva fuente se pausa inmediatamente. El callback de cada fuente captura su identificador y sólo puede completar el evento de esa reproducción; un callback viejo queda sin efecto.

La barra `posición ━━━●━━ duración` se genera sin depender de Discord. Para duración desconocida se muestra un texto explícito. El panel se edita como máximo cada diez segundos y mantiene un único mensaje por guild; `/nowplaying` lo crea o fuerza su edición. Los botones y el comando pasan por las mismas comprobaciones de canal y sesión que el resto de controles.

Se probaron parsing, límites, pausa/reanudación, seek relativo, seek durante pausa, callback viejo, skip/stop y aislamiento por guild junto con la suite anterior. El audio real de YouTube y la interfaz real de Discord siguen requiriendo la prueba manual documentada en el README.
