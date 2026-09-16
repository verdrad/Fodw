import asyncio
import time
from .queue import Queue, MusicError
from .position import PlaybackPosition


class GuildPlayer:
    """One worker per connected guild. All state mutations run on the event loop."""
    def __init__(self, voice, audio, make_source, notify, volume=50, limit=100, *, clock=time.monotonic):
        self.voice = voice
        self.audio = audio
        self.make_source = make_source
        self.notify = notify
        self.queue = Queue(limit)
        self.volume = volume
        self.wake = asyncio.Event()
        self.done = asyncio.Event()
        self.generation = 0
        self.reason = "finished"
        self.closed = False
        self.position = PlaybackPosition(clock)
        self.playback_id = 0
        self.stream_url = None
        self.last_active = time.monotonic()
        self.empty_since = None
        self.disconnected_since = None
        self.task = asyncio.create_task(self._run())

    def add(self, tracks):
        if self.closed:
            raise MusicError("La sesión terminó; volvé a usar /play.")
        self.queue.add(tracks)
        self.last_active = time.monotonic()
        self.wake.set()

    async def _notice(self, kind, track=None):
        try:
            await self.notify(kind, track)
        except Exception:
            # Missing text permissions must not prevent audio or queue advancement.
            pass

    async def _run(self):
        try:
            while not self.closed:
                await self.wake.wait()
                self.wake.clear()
                track = self.queue.current or self.queue.advance()
                while track and not self.closed:
                    generation = self.generation
                    self.done = asyncio.Event()
                    finished = self.done
                    self.reason = "finished"
                    self.position.reset()
                    self.stream_url = None
                    try:
                        url = await self.audio.stream(track)
                        if generation != self.generation:
                            track = self.queue.current or self.queue.advance()
                            continue
                        if self.reason == "skip":
                            track = self.queue.advance("skip")
                            continue
                        source = self.make_source(url, self.volume)
                        self._play_source(source)
                        self.stream_url = url
                        await self._notice("playing", track)
                        await finished.wait()
                        if self.reason == "error":
                            await self._notice("error", track)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        self.reason = "error"
                        await self._notice("error", track)
                    if generation == self.generation:
                        track = self.queue.advance(self.reason)
                    else:
                        track = self.queue.current or self.queue.advance()
                    self.last_active = time.monotonic()
                self.position.reset()
                self.stream_url = None
        finally:
            self.voice.stop()

    def _play_source(self, source, offset=0, paused=False):
        self.playback_id += 1
        playback_id, event = self.playback_id, self.done
        loop = asyncio.get_running_loop()
        def after(error):
            def complete():
                if playback_id == self.playback_id and event is self.done and not event.is_set():
                    if error:
                        self.reason = "error"
                    event.set()
            loop.call_soon_threadsafe(complete)
        try:
            self.voice.play(source, after=after)
            if paused:
                self.voice.pause()
            self.position.start(offset, paused)
        except Exception:
            source.cleanup()
            raise

    def seek(self, seconds):
        track = self.queue.current
        if (not track or not self.stream_url or self.done.is_set() or self.closed
                or not (self.voice.is_playing() or self.voice.is_paused())):
            raise MusicError("No hay una canción lista para cambiar de posición.")
        if not track.duration or track.duration <= 0:
            raise MusicError("Seek no disponible: duración desconocida o transmisión en vivo.")
        if type(seconds) is not int or not 0 <= seconds < track.duration:
            raise MusicError("La posición debe ser mayor o igual a 0 y menor que la duración de la canción.")
        paused = self.paused_at is not None
        try:
            # Prepare first: a constructor failure leaves the old audio untouched.
            source = self.make_source(self.stream_url, self.volume, position=seconds)
        except Exception:
            raise MusicError("No pude preparar el salto de audio; la reproducción actual se conserva.") from None
        # No await in this transaction. Commands and worker run on the same loop.
        # Invalidate BEFORE stop: its delayed callback must never advance the queue.
        self.playback_id += 1
        self.voice.stop()
        try:
            self._play_source(source, seconds, paused)
        except Exception:
            self.playback_id += 1
            self.reason = "error"
            self.done.set()
            raise MusicError("Falló el reinicio de audio; continúo con la siguiente canción.") from None
        return seconds

    def seek_relative(self, delta):
        track = self.queue.current
        if not track or not track.duration or track.duration <= 0:
            raise MusicError("No hay una canción con duración conocida para cambiar de posición.")
        return self.seek(max(0, min(self.progress + delta, track.duration - 1)))

    def skip(self):
        if not self.queue.current:
            raise MusicError("No hay una canción actual.")
        self.reason = "skip"
        self.playback_id += 1
        self.voice.stop()
        self.done.set()

    def previous(self):
        if not self.queue.current:
            raise MusicError("No hay una canción actual.")
        self.generation += 1
        self.playback_id += 1
        self.voice.stop()
        self.done.set()
        return self.queue.previous()

    def stop(self):
        self.generation += 1
        self.playback_id += 1
        self.queue.stop()
        self.voice.stop()
        self.done.set()
        self.position.reset()
        self.stream_url = None
        self.last_active = time.monotonic()

    def pause(self):
        if not self.voice.is_playing():
            raise MusicError("No hay audio reproduciéndose.")
        self.voice.pause()
        self.position.pause()

    def resume(self):
        if not self.voice.is_paused():
            raise MusicError("La reproducción no está pausada.")
        self.voice.resume()
        self.position.resume()

    def set_volume(self, value):
        if not 0 <= value <= 100:
            raise MusicError("El volumen debe estar entre 0 y 100.")
        self.volume = value
        if self.voice.source:
            self.voice.source.volume = value / 100

    @property
    def progress(self):
        seconds = int(self.position.seconds)
        track = self.queue.current
        return min(seconds, track.duration) if track and track.duration else seconds

    @property
    def paused_at(self):
        return self.position.paused_at

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        await self.voice.disconnect(force=True)


class MusicManager:
    def __init__(self):
        self.players: dict[int, GuildPlayer] = {}
        self.locks: dict[int, asyncio.Lock] = {}
        self.revisions: dict[int, int] = {}

    def revision(self, guild_id):
        return self.revisions.get(guild_id, 0)

    def invalidate(self, guild_id):
        self.revisions[guild_id] = self.revision(guild_id) + 1

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    async def close(self):
        await asyncio.gather(*(p.close() for p in self.players.values()), return_exceptions=True)
        self.players.clear()
