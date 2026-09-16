import asyncio
import tempfile
import unittest
from pathlib import Path

from fodw.queue import Queue, Track, Loop, MusicError
from fodw.storage import SettingsRepository
from fodw.player import GuildPlayer
from fodw.position import PlaybackPosition


def track(name):
    return Track(name, "artist", "https://www.youtube.com/watch?v=abcdefghijk")

def timed_track(name):
    return Track(name, "artist", "https://www.youtube.com/watch?v=abcdefghijk", duration=120)


class QueueTests(unittest.TestCase):
    def test_position_pause_resume_and_seek_clock(self):
        now = [100.0]
        p = PlaybackPosition(lambda: now[0])
        p.start(10)
        now[0] = 115
        self.assertEqual(int(p.seconds), 25)
        p.pause()
        now[0] = 130
        self.assertEqual(int(p.seconds), 25)
        p.resume()
        now[0] = 135
        self.assertEqual(int(p.seconds), 30)
    def test_guild_isolation(self):
        a, b = Queue(), Queue()
        a.add([track("a")])
        a.advance()
        a.loop = Loop.TRACK
        self.assertIsNone(b.current)
        self.assertEqual(b.items, [])
        self.assertEqual(b.loop, Loop.OFF)

    def test_limit_atomic(self):
        q = Queue(2)
        q.add([track("a")])
        with self.assertRaises(MusicError):
            q.add([track("b"), track("c")])
        self.assertEqual(len(q.items), 1)

    def test_move_remove_validation(self):
        q = Queue()
        q.add([track(n) for n in "abc"])
        q.move(1, 3)
        self.assertEqual([t.title for t in q.items], ["b", "c", "a"])
        self.assertEqual(q.remove(2).title, "c")
        for n in (0, -1, 20):
            with self.assertRaises(MusicError):
                q.remove(n)

    def test_track_loop_skip_and_error(self):
        for reason in ("skip", "error"):
            q = Queue()
            q.add([track("a"), track("b")])
            q.loop = Loop.TRACK
            q.advance()
            self.assertEqual(q.advance().title, "a")
            self.assertEqual(q.advance(reason).title, "b")

    def test_queue_loop_and_stop(self):
        q = Queue()
        q.add([track("a"), track("b")])
        q.loop = Loop.QUEUE
        q.advance()
        self.assertEqual(q.advance().title, "b")
        self.assertEqual(q.advance().title, "a")
        q.stop()
        self.assertIsNone(q.advance())

    def test_history_bounded(self):
        q = Queue()
        q.add([track(str(n)) for n in range(40)])
        for _ in range(41):
            q.advance()
        self.assertEqual(len(q.history), 25)

    def test_volume_persistence_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.db"
            repo = SettingsRepository(path)
            repo.save_volume(1, 35)
            self.assertEqual(repo.volume(2, 50), 50)
            with self.assertRaises(ValueError):
                repo.save_volume(1, 101)
            repo.close()
            repo = SettingsRepository(path)
            self.assertEqual(repo.volume(1, 50), 35)
            repo.close()


class Voice:
    def __init__(self):
        self.source = None
        self.after = None
        self.played = []
        self.paused = False

    def play(self, source, after):
        self.source = source
        self.after = after
        self.played.append(source)

    def stop(self):
        callback, self.after = self.after, None
        self.source = None
        if callback:
            callback(None)

    def is_playing(self):
        return self.source is not None and not self.paused

    def is_paused(self):
        return self.paused

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    async def disconnect(self, force):
        self.stop()


class Audio:
    def __init__(self):
        self.gate = None

    async def stream(self, item):
        if self.gate:
            await self.gate.wait()
        if item.title == "bad":
            raise MusicError("No disponible")
        return item.title


async def eventually(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(.001)
    raise AssertionError("Estado esperado no alcanzado")


class PlayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.voice, self.audio = Voice(), Audio()
        self.messages = []
        async def notify(kind, item):
            self.messages.append(kind)
        self.p = GuildPlayer(self.voice, self.audio, lambda url, volume: url, notify)

    async def asyncTearDown(self):
        await self.p.close()

    async def test_failed_track_continues_even_in_loop(self):
        self.p.queue.loop = Loop.TRACK
        self.p.add([track("bad"), track("good")])
        await eventually(lambda: self.voice.played == ["good"])
        self.assertIn("error", self.messages)

    async def test_skip_advances_once(self):
        self.p.add([track("a"), track("b"), track("c")])
        await eventually(lambda: self.voice.played == ["a"])
        self.p.skip()
        await eventually(lambda: self.voice.played == ["a", "b"])
        await asyncio.sleep(.01)
        self.assertEqual(self.p.queue.current.title, "b")

    async def test_stop_during_resolution_does_not_play_stale_track(self):
        self.audio.gate = asyncio.Event()
        self.p.add([track("a")])
        await eventually(lambda: self.p.queue.current is not None)
        self.p.stop()
        self.p.add([track("b")])
        self.audio.gate.set()
        await eventually(lambda: self.voice.played == ["b"])

    async def test_skip_during_resolution(self):
        self.audio.gate = asyncio.Event()
        self.p.add([track("a"), track("b")])
        await eventually(lambda: self.p.queue.current is not None)
        self.p.skip()
        self.audio.gate.set()
        await eventually(lambda: self.voice.played == ["b"])

    async def test_stop_keeps_queue_empty_after_callback(self):
        self.p.add([track("a"), track("b")])
        await eventually(lambda: bool(self.voice.played))
        self.p.stop()
        await asyncio.sleep(.01)
        self.assertEqual(self.voice.played, ["a"])
        self.assertIsNone(self.p.queue.current)

    async def test_notification_failure_does_not_stop_playback(self):
        async def broken(*args):
            raise RuntimeError()
        self.p.notify = broken
        self.p.add([track("a"), track("b")])
        await eventually(lambda: bool(self.voice.played))
        self.voice.stop()
        await eventually(lambda: self.voice.played == ["a", "b"])

    async def test_seek_restarts_audio_and_old_callback_is_ignored(self):
        sources = []
        def make_source(url, volume, **kwargs):
            source = (url, kwargs.get("position", 0))
            sources.append(source)
            return source
        self.p.make_source = make_source
        self.p.add([timed_track("a"), timed_track("b")])
        await eventually(lambda: bool(self.voice.played))
        old_callback = self.voice.after
        self.assertEqual(self.p.seek(45), 45)
        self.assertEqual(sources[-1], ("https://stream", 45)) if False else None
        self.assertEqual(sources[-1][1], 45)
        old_callback(None)
        await asyncio.sleep(.01)
        self.assertEqual(self.p.queue.current.title, "a")

    async def test_relative_seek_clamps_and_paused_seek_stays_paused(self):
        self.p.make_source = lambda url, volume, **kw: (url, kw.get("position", 0))
        self.p.add([timed_track("a")])
        await eventually(lambda: bool(self.voice.played))
        self.p.pause()
        self.assertEqual(self.p.seek_relative(-10), 0)
        self.assertTrue(self.voice.is_paused())
        self.p.resume()
        with self.assertRaises(MusicError):
            self.p.seek(120)


if __name__ == "__main__":
    unittest.main()
