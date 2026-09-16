"""Metadata resolution and playable audio are separate operations.

Only canonical YouTube URLs reach the extractor. No arbitrary URL downloader,
cookies, credentials, geo bypass or remote JS components are configured.
"""
import asyncio
from dataclasses import replace
import re
import sys
import json
from typing import Protocol
from urllib.parse import urlparse, parse_qs

import aiohttp

from .queue import Track, MusicError


class AudioProvider(Protocol):
    async def resolve(self, query: str, requester: int, count: int = 1) -> list[Track]: ...
    async def stream(self, track: Track) -> str: ...


def youtube_query(query: str) -> str:
    query = query.strip()
    if not query or len(query) > 500:
        raise MusicError("Ingresá una búsqueda o URL de hasta 500 caracteres.")
    if "://" not in query:
        if query.startswith(("/", "-")) or ":" in query:
            raise MusicError("Formato de búsqueda no admitido.")
        return query
    parsed = urlparse(query)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise MusicError("Usá una URL HTTPS de YouTube o Spotify.")
    host = parsed.hostname
    if host == "youtu.be":
        video = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        args = parse_qs(parsed.query)
        video = args.get("v", [""])[0]
        if not video and parsed.path.startswith(("/shorts/", "/live/")):
            video = parsed.path.split("/")[2]
        if not video:
            playlist = args.get("list", [""])[0]
            if re.fullmatch(r"[\w-]{10,100}", playlist):
                return "https://www.youtube.com/playlist?list=" + playlist
    else:
        raise MusicError("Esta fuente todavía no está habilitada.")
    if not re.fullmatch(r"[\w-]{11}", video):
        raise MusicError("URL de YouTube inválida.")
    return "https://www.youtube.com/watch?v=" + video


class YouTubeProvider:
    def __init__(self, enabled, limit):
        self.enabled = enabled
        self.limit = limit
        self.slots = asyncio.Semaphore(2)

    async def _extract(self, target, flat):
        if not self.enabled:
            raise MusicError("YouTube está deshabilitado. El administrador debe configurar YOUTUBE_ENABLED.")
        # A process is cancellable; timed-out extraction cannot keep a worker busy.
        args = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-warnings", "--quiet",
                "--skip-download", "--dump-single-json", "--socket-timeout", "10",
                "--retries", "1", "--extractor-retries", "1", "--no-geo-bypass",
                "--playlist-end", str(self.limit), "--no-check-formats"]
        args += ["--flat-playlist", "--ignore-errors"] if flat else ["--no-playlist", "-f", "bestaudio/best"]
        async with self.slots:
            proc = await asyncio.create_subprocess_exec(*args, "--", target,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                output, _ = await asyncio.wait_for(proc.communicate(), 40)
                if proc.returncode or not output:
                    raise MusicError("El proveedor no pudo resolver el contenido; puede estar restringido o no disponible.")
                return json.loads(output)
            except (TimeoutError, json.JSONDecodeError):
                raise MusicError("El proveedor tardó demasiado o devolvió una respuesta inválida.") from None
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

    async def resolve(self, query, requester, count=1):
        target = youtube_query(query)
        if not target.startswith("https://"):
            target = f"ytsearch{count}:{target}"
        data = await self._extract(target, True)
        entries = data.get("entries", [data])
        result = []
        for item in entries or []:
            if not item or not re.fullmatch(r"[\w-]{11}", item.get("id", "")):
                continue
            if item.get("availability") in {"private", "premium_only", "subscriber_only"}:
                continue
            thumbs = item.get("thumbnails") or []
            result.append(Track(str(item.get("title") or "Sin título")[:200],
                str(item.get("artist") or item.get("uploader") or item.get("channel") or "Artista desconocido")[:120],
                "https://www.youtube.com/watch?v=" + item["id"],
                int(item["duration"]) if item.get("duration") else None,
                item.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None), requester))
        if not result:
            raise MusicError("No encontré canciones disponibles.")
        return result[:self.limit]

    async def autocomplete(self, query, limit=5):
        """Obtiene sugerencias de texto; no inicia yt-dlp ni resuelve audio."""
        if not self.enabled or len(query.strip()) < 2:
            return []
        try:
            timeout = aiohttp.ClientTimeout(total=0.8, connect=0.4)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://suggestqueries.google.com/complete/search",
                                       params={"client": "firefox", "ds": "yt", "q": query.strip()}) as response:
                    if response.status != 200:
                        return []
                    data = await response.json(content_type=None)
            suggestions = data[1] if isinstance(data, list) and len(data) > 1 else []
            results = []
            for suggestion in suggestions:
                value = str(suggestion).strip()
                if value and ":" not in value and value not in {item[2] for item in results}:
                    results.append((value[:200], "YouTube", value[:500]))
            return results[:limit]
        except Exception:
            return []

    async def stream(self, track):
        data = await self._extract(youtube_query(track.url), False)
        url = data.get("url", "")
        parsed = urlparse(url)
        # Only the media CDN is allowed into FFmpeg (no files or LAN URLs).
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".googlevideo.com"):
            raise MusicError("El proveedor no devolvió una fuente de audio admitida.")
        return url


class SpotifyProvider:
    def __init__(self, session, client_id, secret):
        self.session = session
        self.client_id = client_id
        self.secret = secret

    async def metadata(self, url):
        parsed = urlparse(url)
        match = re.fullmatch(r"/(?:intl-[a-z]{2}/)?track/([A-Za-z0-9]{22})/?", parsed.path)
        if parsed.scheme != "https" or parsed.hostname != "open.spotify.com" or not match:
            raise MusicError("Spotify v0.1 admite enlaces de canciones; álbumes y playlists están pendientes.")
        if not self.client_id or not self.secret:
            raise MusicError("Faltan SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET.")
        try:
            async with self.session.post("https://accounts.spotify.com/api/token",
                        auth=aiohttp.BasicAuth(self.client_id, self.secret),
                        data={"grant_type": "client_credentials"}) as response:
                if response.status != 200:
                    raise MusicError("Spotify no pudo autenticar la aplicación.")
                token = (await response.json())["access_token"]
            async with self.session.get("https://api.spotify.com/v1/tracks/" + match[1],
                        headers={"Authorization": "Bearer " + token}) as response:
                if response.status != 200:
                    raise MusicError("Spotify no entregó la canción (acceso, límite o disponibilidad).")
                data = await response.json()
            return data["name"], ", ".join(a["name"] for a in data["artists"])
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError):
            raise MusicError("No se pudo consultar Spotify en este momento.") from None


class TrackResolver:
    def __init__(self, audio: AudioProvider, spotify: SpotifyProvider):
        self.audio = audio
        self.spotify = spotify

    async def resolve(self, query, requester, count=1):
        if urlparse(query).hostname == "open.spotify.com":
            title, artist = await self.spotify.metadata(query)
            tracks = await self.audio.resolve(f"{artist} {title}", requester, 1)
            return [replace(t, source="YouTube · búsqueda por metadatos de Spotify") for t in tracks]
        return await self.audio.resolve(query, requester, count)

    async def autocomplete(self, query, limit=5):
        if urlparse(query).scheme or urlparse(query).hostname:
            return []
        return await self.audio.autocomplete(query, limit)
