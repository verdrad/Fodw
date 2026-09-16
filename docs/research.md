# Investigación y decisiones — 2026-09-15

Fuentes primarias consultadas antes de implementar:

- [FlaviBot: organización pública](https://github.com/flavibot) y [ficha de Discord](https://discord.com/discovery/applications/684773505157431347): referencias funcionales de música, playlists y autoplay. No se verificó código del bot principal ni una licencia que permita reutilizarlo; **no se reutilizó código**. No asumimos que su núcleo usa Lavalink por el solo hecho de mencionarse en los requisitos.
- [discord.py changelog](https://discordpy.readthedocs.io/en/stable/whats_new.html): 2.7.0 agrega DAVE; 2.7.1 incluye diagnóstico de davey. Se fija 2.7.1 para evitar versiones de voz anteriores. Licencia de la biblioteca: MIT, consultar el paquete instalado.
- [Discord Voice](https://docs.discord.com/developers/topics/voice-connections): DAVE/E2EE requerido desde marzo de 2026. Es una condición de compatibilidad, no una función opcional.
- [discord.js voice](https://discordjs.dev/docs/packages/voice/main): alternativa vigente con DAVE y dependencias de audio. La página consultada pide Node.js 24.17.0+. No se instaló porque se eligió Python.
- [Lavalink](https://lavalink.dev/getting-started/): servicio de audio separado. Su costo adicional de despliegue no se justifica todavía para este MVP. Una migración futura debe evaluar versión, Java, plugins y licencias por separado.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp): versión fijada 2026.08.19, soporte completo de YouTube requiere runtime JavaScript y EJS. Proyecto bajo Unlicense con licencias adicionales según dependencias/distribución. No se copió código del repositorio, se consume como dependencia. No hay compromiso de estabilidad frente a cambios del proveedor.
- [Spotify Get Track](https://developer.spotify.com/documentation/web-api/reference/get-track) y [Client Credentials](https://developer.spotify.com/documentation/web-api/tutorials/client-credentials-flow): metadatos mediante credenciales de aplicación. El endpoint no concede acceso al audio completo ni derechos de reproducción. La disponibilidad de endpoints depende de permisos/modo de la aplicación.
- [FFmpeg](https://ffmpeg.org/legal.html): licencia LGPL/GPL según build; no se distribuye un binario con Fodw. Verificar la licencia del build elegido si se redistribuye posteriormente.

Credenciales mínimas: token de Discord. Spotify es opcional y requiere client ID/secret. No se requiere una API key de YouTube en este adaptador; yt-dlp no es una API oficial de YouTube. La habilitación del proveedor no implica autorización del contenido ni aceptación de todos los usos por parte de la plataforma.

No se garantiza menor RAM que Node o Lavalink sin un benchmark. La elección prioriza simplicidad de despliegue, aislamiento por guild y facilidad de mantenimiento. El módulo AudioProvider permite reemplazar la integración sin reescribir la cola.

Plan posterior: añadir pruebas de voz en un servidor real, medir recursos; luego proveedores de playlists Spotify con paginación/límites y coincidencias mejores; implementar estrategia de autoplay explícita; lyrics con un proveedor que conceda derechos adecuados; persistencia de historial opt-in con retención acotada. Nunca conectar Spotify directamente al reproductor de audio.
