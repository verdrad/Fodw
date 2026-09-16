"""Offline adapter checks; install project dependencies before running."""
import unittest
from unittest.mock import AsyncMock, Mock, patch
import discord
from tempfile import TemporaryDirectory
from pathlib import Path
from fodw.providers import youtube_query, TrackResolver
from fodw.queue import MusicError, Track, Loop
from fodw.config import Config
from fodw.discord_app import Fodw
from fodw.discord_app import Controls
from fodw.position import parse_position, progress_bar
from fodw.audio import FFmpegSourceFactory
from fodw.now_playing import NowPlayingPanel
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace


class ProviderTests(unittest.TestCase):
    def test_controls_stop_is_view_method_not_button(self):
        self.assertIs(Controls.stop, discord.ui.View.stop)
        self.assertIn("stop_button", Controls.__view_children_items__)
    def test_ffmpeg_seek_uses_before_options_without_stdin_or_int_stderr(self):
        with patch("fodw.audio.discord.FFmpegPCMAudio") as ffmpeg, \
             patch("fodw.audio.discord.PCMVolumeTransformer"):
            ffmpeg.return_value = Mock(is_opus=lambda: False)
            FFmpegSourceFactory("ffmpeg")("https://media.example/audio", 50, position=90)
            kwargs = ffmpeg.call_args.kwargs
            self.assertIn("-ss 90", kwargs["before_options"])
            self.assertNotIn("pipe", kwargs)
            self.assertNotIn("stderr", kwargs)
    def test_position_parsing_and_bar(self):
        self.assertEqual(parse_position("1:30"), 90)
        self.assertEqual(parse_position("45"), 45)
        self.assertEqual(parse_position("01:25"), 85)
        self.assertIn("1:30", progress_bar(90, 210))
        for value in ("-1", "1:60", "abc", "1:2", "1:999"):
            with self.subTest(value=value), self.assertRaises(MusicError):
                parse_position(value)

    def test_normalization(self):
        self.assertEqual(youtube_query("https://youtu.be/abcdefghijk?t=42"), "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(youtube_query("Linkin Park Numb"), "Linkin Park Numb")

    def test_reject_untrusted_urls(self):
        for value in ("https://localhost/a", "file:///etc/passwd", "https://youtube.com.evil.test/watch?v=abcdefghijk", "https://user:pass@youtube.com/watch?v=abcdefghijk", "--help", "ytsearch:hi"):
            with self.subTest(value=value), self.assertRaises(MusicError):
                youtube_query(value)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_new_track_deletes_old_and_posts_once(self):
        message = Mock(created_at=datetime.now(timezone.utc)); message.edit = AsyncMock(); message.delete = AsyncMock()
        channel = Mock(); channel.send = AsyncMock(return_value=message)
        player = SimpleNamespace(queue=SimpleNamespace(current=Track("A", "Artist", "https://x", 120, requester=1), loop=Loop.OFF, items=[]), closed=False, paused_at=None, progress=0, volume=50)
        panel = NowPlayingPanel(channel, player, lambda: None)
        await panel.refresh(force=True)
        player.queue.current = Track("B", "Artist", "https://x", 120, requester=1)
        await panel.new_track()
        self.assertEqual(channel.send.await_count, 2)
        message.delete.assert_awaited_once()

    async def test_panel_refresh_edits_existing_and_no_duplicate(self):
        message = Mock(created_at=datetime.now(timezone.utc)); message.edit = AsyncMock(); message.delete = AsyncMock()
        channel = Mock(); channel.send = AsyncMock(return_value=message)
        player = SimpleNamespace(queue=SimpleNamespace(current=Track("A", "Artist", "https://x", 120, requester=1), loop=Loop.OFF, items=[]), closed=False, paused_at=None, progress=0, volume=50)
        panel = NowPlayingPanel(channel, player, lambda: None)
        await panel.refresh(force=True)
        panel.last_move -= 120
        await panel.refresh()
        self.assertEqual(channel.send.await_count, 1)
        message.edit.assert_not_awaited()
        player.progress = 10
        await panel.refresh()
        message.edit.assert_awaited_once()

    async def test_panel_reposts_only_after_age_and_cooldown(self):
        old = Mock(created_at=datetime.now(timezone.utc) - timedelta(seconds=120)); old.edit = AsyncMock(); old.delete = AsyncMock()
        new = Mock(created_at=datetime.now(timezone.utc)); new.edit = AsyncMock(); new.delete = AsyncMock()
        channel = Mock(); channel.send = AsyncMock(side_effect=[old, new])
        player = SimpleNamespace(queue=SimpleNamespace(current=Track("A", "Artist", "https://x", 120, requester=1), loop=Loop.OFF, items=[]), closed=False, paused_at=None, progress=0, volume=50)
        panel = NowPlayingPanel(channel, player, lambda: None, move_after=90)
        await panel.refresh(force=True)
        panel.last_move -= 120
        await panel.refresh()
        self.assertEqual(channel.send.await_count, 2)
        old.delete.assert_awaited_once()
    def test_controls_have_two_rows_and_spanish_labels(self):
        names = set(Controls.__view_children_items__)
        self.assertTrue({"volume_down", "previous_button", "toggle", "skip", "volume_up",
                         "shuffle", "loop", "stop_button", "seek_button", "queue_button"} <= names)
        self.assertNotIn("stop", names)

    def test_client_connect_is_inherited_and_overrides_are_intentional(self):
        self.assertIs(Fodw.connect, discord.Client.connect)
        overrides = {name for name in Fodw.__dict__
                     if not name.startswith("__") and callable(getattr(discord.Client, name, None))}
        self.assertEqual(overrides, {"setup_hook", "close"})

    async def test_start_uses_discord_connection_with_reconnect(self):
        with TemporaryDirectory() as tmp:
            config = Config("fake", "ffmpeg", str(Path(tmp) / "db"), 50, 180, 60, 100, False, "", "", None)
            bot = Fodw(config)
            try:
                # No login or network access: exercise Client.start's real dispatch.
                with patch.object(bot, "login", new_callable=AsyncMock), \
                     patch.object(discord.Client, "connect", autospec=True) as gateway:
                    for reconnect in (True, False):
                        await bot.start("test-placeholder", reconnect=reconnect)
                        gateway.assert_awaited_with(bot, reconnect=reconnect)
            finally:
                await bot.close()

    async def test_enqueue_and_join_use_voice_connection(self):
        with TemporaryDirectory() as tmp:
            config = Config("fake", "ffmpeg", str(Path(tmp) / "db"), 50, 180, 60, 100, False, "", "", None)
            bot = Fodw(config)
            interaction = SimpleNamespace(guild_id=1, response=SimpleNamespace(defer=AsyncMock()),
                                          followup=SimpleNamespace(send=AsyncMock()))
            player = Mock()
            try:
                with patch.object(bot, "connect_voice", new_callable=AsyncMock, return_value=player) as voice, \
                     patch.object(discord.Client, "connect", autospec=True) as gateway:
                    await bot.enqueue(interaction, ["track-placeholder"])
                    player.add.assert_called_once_with(["track-placeholder"])
                    await bot.tree.get_command("join").callback(interaction)
                    self.assertEqual(voice.await_count, 2)
                    voice.assert_awaited_with(interaction)
                    gateway.assert_not_awaited()
            finally:
                await bot.close()

    async def test_pending_play_cancelled_by_session_stop(self):
        with TemporaryDirectory() as tmp:
            config = Config("fake", "ffmpeg", str(Path(tmp) / "db"), 50, 180, 60, 100, False, "", "", None)
            bot = Fodw(config)
            try:
                revision = bot.manager.revision(1)
                bot.manager.invalidate(1)
                with self.assertRaises(MusicError):
                    await bot.enqueue(SimpleNamespace(guild_id=1), [], revision)
                self.assertEqual(bot.manager.revision(2), 0)
            finally:
                await bot.close()

    async def test_all_commands_serialize_without_discord_login(self):
        with TemporaryDirectory() as tmp:
            config = Config("fake", "ffmpeg", str(Path(tmp) / "db"), 50, 180, 60, 100, False, "", "", None)
            bot = Fodw(config)
            try:
                commands = bot.tree.get_commands()
                self.assertEqual({c.name for c in commands}, {"play", "search", "join", "leave", "pause", "resume", "skip", "stop", "clear", "shuffle", "replay", "nowplaying", "queue", "remove", "move", "loop", "volume", "history", "seek"})
                for command in commands:
                    payload = command.to_dict(bot.tree)
                    self.assertTrue(payload["name"])
                    self.assertTrue(command.guild_only)
                self.assertTrue(commands[0].name)
            finally:
                await bot.close()

    async def test_play_autocomplete_only_resolves_metadata(self):
        with TemporaryDirectory() as tmp:
            config = Config("fake", "ffmpeg", str(Path(tmp) / "db"), 50, 180, 60, 100, False, "", "", None)
            bot = Fodw(config)
            class Resolver:
                async def resolve(self, query, requester, count):
                    self.args = (query, requester, count)
                    return [Track("Numb", "Linkin Park", "https://www.youtube.com/watch?v=abcdefghijk")]
            resolver = Resolver(); bot.resolver = resolver
            try:
                callback = bot.tree.get_command("play")._params["query"].autocomplete
                result = await callback(SimpleNamespace(user=SimpleNamespace(id=7)), "numb li")
                self.assertEqual(result[0].value, "https://www.youtube.com/watch?v=abcdefghijk")
                self.assertEqual(resolver.args, ("numb li", 7, 5))
            finally:
                await bot.close()

    async def test_spotify_metadata_is_not_audio(self):
        class Spotify:
            async def metadata(self, url):
                return "Song", "Artist"
        class Audio:
            async def resolve(self, query, requester, count):
                self.query = query
                return [Track("match", "artist", "https://www.youtube.com/watch?v=abcdefghijk")]
        audio = Audio()
        result = await TrackResolver(audio, Spotify()).resolve("https://open.spotify.com/track/test", 1)
        self.assertEqual(audio.query, "Artist Song")
        self.assertIn("youtube.com", result[0].url)
