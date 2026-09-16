import asyncio
from contextlib import suppress
import logging
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from .player import GuildPlayer, MusicManager
from .providers import YouTubeProvider, SpotifyProvider, TrackResolver
from .queue import MusicError, Loop
from .storage import SettingsRepository
from .audio import FFmpegSourceFactory
from .position import duration, parse_position
from .now_playing import now_embed, NowPlayingPanel


class Controls(discord.ui.View):
    def __init__(self, bot, guild_id, player):
        super().__init__(timeout=900)
        self.bot, self.guild_id, self.player = bot, guild_id, player

    async def update_panel(self):
        panel = self.bot.panels.get(self.guild_id)
        if panel:
            await panel.refresh(force=True)

    async def interaction_check(self, interaction):
        try:
            if self.bot.manager.players.get(self.guild_id) is not self.player:
                raise MusicError("Estos controles pertenecen a una sesión anterior.")
            self.bot.get_player(interaction)
            return True
        except MusicError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return False

    async def on_error(self, interaction, error, item):
        await self.bot.report(interaction, error)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        if p.voice.is_paused():
            p.resume(); button.label = "Pausar"; message = "Reproducción reanudada."
        else:
            p.pause(); button.label = "Reanudar"; message = "Reproducción pausada."
        await self.update_panel()
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="Anterior", emoji="⏮️", row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.previous(); await self.update_panel()
        await interaction.response.send_message("Reproduciendo la canción anterior.", ephemeral=True)

    @discord.ui.button(label="-", emoji="🔉", row=0)
    async def volume_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        value = max(0, self.player.volume - 10); self.player.set_volume(value)
        self.bot.repo.save_volume(self.guild_id, value); await self.update_panel()
        await interaction.response.send_message(f"Volumen: {value}%", ephemeral=True)

    @discord.ui.button(label="+", emoji="🔊", row=0)
    async def volume_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        value = min(100, self.player.volume + 10); self.player.set_volume(value)
        self.bot.repo.save_volume(self.guild_id, value); await self.update_panel()
        await interaction.response.send_message(f"Volumen: {value}%", ephemeral=True)

    @discord.ui.button(emoji="⏭️", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.skip()
        await self.update_panel()
        await interaction.response.send_message("Canción saltada.", ephemeral=True)

    @discord.ui.button(emoji="🔀", row=1)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.queue.shuffle()
        await self.update_panel()
        await interaction.response.send_message("Cola mezclada.", ephemeral=True)

    @discord.ui.button(emoji="🔁", row=1)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        values = list(Loop)
        self.player.queue.loop = values[(values.index(self.player.queue.loop) + 1) % 3]
        await self.update_panel()
        await interaction.response.send_message(f"Repetición: {self.player.queue.loop.value}", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=1)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.manager.invalidate(self.guild_id)
        self.player.stop()
        await self.update_panel()
        await interaction.response.send_message("Reproducción detenida y cola vaciada.", ephemeral=True)

    @discord.ui.button(label="🎯 Ir a...", row=1)
    async def seek_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SeekModal(self.bot, self.guild_id, self.player))

    @discord.ui.button(label="📜 Cola", row=1)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=queue_embed(self.player), ephemeral=True)


class SeekModal(discord.ui.Modal, title="Ir a una posición"):
    position = discord.ui.TextInput(label="Posición", placeholder="45, 1:30 o 2:05", max_length=12)

    def __init__(self, bot, guild_id, player):
        super().__init__(); self.bot, self.guild_id, self.player = bot, guild_id, player

    async def on_submit(self, interaction: discord.Interaction):
        self.bot.get_player(interaction)
        target = self.player.seek(parse_position(str(self.position)))
        panel = self.bot.panels.get(self.guild_id)
        if panel: await panel.refresh(force=True)
        await interaction.response.send_message(f"⏩ Saltando a {duration(target)}.", ephemeral=True)


def queue_embed(player):
    lines = []
    if player.queue.current:
        lines.append(f"▶️ **{player.queue.current.title}** — {player.queue.current.artist}")
    lines.extend(f"{n}. {track.title} — {track.artist}" for n, track in enumerate(player.queue.items, 1))
    return discord.Embed(title="📜 Cola", description="\n".join(lines) or "La cola está vacía.", color=0x7755EE)


class SearchView(discord.ui.View):
    def __init__(self, bot, requester, tracks):
        super().__init__(timeout=60)
        self.bot, self.requester, self.tracks = bot, requester, tracks
        self.used = False
        select = discord.ui.Select(placeholder="Elegí una canción", options=[
            discord.SelectOption(label=t.title[:100], description=t.artist[:100], value=str(n))
            for n, t in enumerate(tracks)])
        select.callback = self.choose
        self.add_item(select)

    async def choose(self, interaction):
        if interaction.user.id != self.requester:
            await interaction.response.send_message("Esta búsqueda pertenece a otra persona.", ephemeral=True)
            return
        if self.used:
            await interaction.response.send_message("Esta selección ya fue utilizada.", ephemeral=True)
            return
        self.used = True
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.enqueue(interaction, [self.tracks[int(interaction.data["values"][0])]])
            await interaction.edit_original_response(content="Canción agregada.", view=None)
            self.stop()
        except Exception as error:
            self.used = False
            await self.bot.report(interaction, error)


class Fodw(discord.Client):
    def __init__(self, config):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.manager = MusicManager()
        self.repo = SettingsRepository(config.database)
        self.session = None
        self.pending: set[int] = set()
        self.panels = {}
        self.register_commands()
        self.tree.on_error = self.report

    async def setup_hook(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        self.audio = YouTubeProvider(self.config.youtube, self.config.max_queue)
        self.resolver = TrackResolver(self.audio, SpotifyProvider(self.session, self.config.spotify_id, self.config.spotify_secret))
        if self.config.dev_guild:
            guild = discord.Object(id=self.config.dev_guild)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.cleanup_players.start()
        self.update_panels.start()

    async def on_ready(self):
        logging.info("Fodw conectado; %s servidores", len(self.guilds))

    async def report(self, interaction, error):
        error = getattr(error, "original", error)
        if isinstance(error, MusicError):
            message = str(error)
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = f"Esperá {error.retry_after:.0f} segundos antes de repetir."
        else:
            logging.warning("Operación fallida: %s", type(error).__name__)
            message = "No pude completar la operación. Revisá permisos de texto/voz o intentá nuevamente."
        with suppress(discord.HTTPException):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    def channel_for(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise MusicError("Este comando sólo funciona dentro de un servidor.")
        channel = interaction.user.voice.channel if interaction.user.voice else None
        if not isinstance(channel, discord.VoiceChannel):
            raise MusicError("Entrá en un canal de voz normal para controlar Fodw.")
        return channel

    def get_player(self, interaction):
        channel = self.channel_for(interaction)
        player = self.manager.players.get(interaction.guild_id)
        if not player or player.closed or not player.voice.is_connected():
            raise MusicError("Fodw no está conectado. Usá /play o /join.")
        if player.voice.channel.id != channel.id:
            raise MusicError("Tenés que estar en el mismo canal de voz que Fodw.")
        return player

    async def connect_voice(self, interaction):
        channel = self.channel_for(interaction)
        player = self.manager.players.get(interaction.guild_id)
        if player and not player.closed and player.voice.is_connected():
            return self.get_player(interaction)
        if player:
            await player.close()
            self.manager.players.pop(interaction.guild_id, None)
        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.view_channel and permissions.connect and permissions.speak):
            raise MusicError("Necesito Ver canal, Conectar y Hablar en ese canal de voz.")
        voice = await channel.connect(timeout=20, reconnect=True, self_deaf=True)
        source = FFmpegSourceFactory(self.config.ffmpeg)
        async def notify(kind, track):
            if kind == "playing":
                await panel.new_track()
            else:
                await interaction.channel.send("No pude reproducir una canción; continúo con la siguiente.")
        player = GuildPlayer(voice, self.audio, source, notify,
            self.repo.volume(interaction.guild_id, self.config.volume), self.config.max_queue)
        self.manager.players[interaction.guild_id] = player
        panel = NowPlayingPanel(interaction.channel, player, lambda: Controls(self, interaction.guild_id, player))
        self.panels[interaction.guild_id] = panel
        return player

    async def enqueue(self, interaction, tracks, revision=None):
        async with self.manager.lock(interaction.guild_id):
            if revision is not None and revision != self.manager.revision(interaction.guild_id):
                raise MusicError("La búsqueda se canceló porque la sesión fue detenida o cerrada.")
            player = await self.connect_voice(interaction)
            player.add(tracks)

    @tasks.loop(seconds=5)
    async def cleanup_players(self):
        for guild_id, player in list(self.manager.players.items()):
            async with self.manager.lock(guild_id):
                if self.manager.players.get(guild_id) is not player:
                    continue
                now = time.monotonic()
                humans = any(not m.bot for m in player.voice.channel.members) if player.voice.channel else False
                player.empty_since = None if humans else (player.empty_since or now)
                empty = player.empty_since is not None and now - player.empty_since >= self.config.empty
                idle = player.queue.current is None and now - player.last_active >= self.config.idle
                paused_idle = player.paused_at is not None and now - player.paused_at >= self.config.idle
                player.disconnected_since = None if player.voice.is_connected() else (player.disconnected_since or now)
                disconnected = player.disconnected_since is not None and now - player.disconnected_since >= 30
                if empty or idle or paused_idle or disconnected:
                    self.manager.invalidate(guild_id)
                    with suppress(Exception):
                        await player.close()
                    self.manager.players.pop(guild_id, None)
                    panel = self.panels.pop(guild_id, None)
                    if panel:
                        with suppress(discord.HTTPException):
                            await panel.finish()

    @tasks.loop(seconds=10)
    async def update_panels(self):
        for panel in list(self.panels.values()):
            try:
                await panel.refresh()
            except Exception as error:
                logging.exception("No se pudo actualizar el reproductor (%s)", type(error).__name__)

    @update_panels.before_loop
    async def before_panels(self):
        await self.wait_until_ready()

    @cleanup_players.before_loop
    async def before_cleanup(self):
        await self.wait_until_ready()

    async def close(self):
        self.cleanup_players.cancel()
        self.update_panels.cancel()
        await self.manager.close()
        for panel in self.panels.values():
            if panel.view:
                panel.view.stop()
        self.panels.clear()
        if self.session:
            await self.session.close()
        self.repo.close()
        await super().close()

    def register_commands(self):
        tree = self.tree

        @tree.command(name="play", description="Buscar o agregar una canción/playlist compatible")
        @app_commands.guild_only()
        @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
        async def play(i: discord.Interaction, query: str):
            self.channel_for(i)
            if i.guild_id in self.pending:
                raise MusicError("Ya hay una búsqueda pendiente en este servidor.")
            self.pending.add(i.guild_id)
            revision = self.manager.revision(i.guild_id)
            try:
                await i.response.defer(thinking=True)
                tracks = await self.resolver.resolve(query, i.user.id)
                await self.enqueue(i, tracks, revision)
                await i.followup.send(f"Agregadas {len(tracks)} canción(es). Las playlists se limitan a {self.config.max_queue}; entradas no disponibles pueden omitirse.")
            finally:
                self.pending.discard(i.guild_id)

        @play.autocomplete("query")
        async def play_autocomplete(i: discord.Interaction, current: str):
            text = current.strip()
            if len(text) < 2 or "://" in text:
                return []
            try:
                tracks = await asyncio.wait_for(
                    self.resolver.resolve(text, i.user.id, 5), timeout=2.0)
                return [app_commands.Choice(name=f"🎵 {t.title} — {t.artist}"[:100], value=t.url)
                        for t in tracks[:25]]
            except Exception:
                return []

        @tree.command(name="search", description="Buscar cinco resultados y elegir")
        @app_commands.guild_only()
        @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
        async def search(i: discord.Interaction, query: str):
            self.channel_for(i)
            if i.guild_id in self.pending:
                raise MusicError("Ya hay una búsqueda pendiente en este servidor.")
            self.pending.add(i.guild_id)
            try:
                await i.response.defer(ephemeral=True)
                tracks = await self.resolver.resolve(query, i.user.id, 5)
                await i.followup.send("Elegí un resultado (vence en 60 segundos).", view=SearchView(self, i.user.id, tracks[:5]), ephemeral=True)
            finally:
                self.pending.discard(i.guild_id)

        @tree.command(name="join", description="Conectar Fodw a tu canal")
        @app_commands.guild_only()
        async def join(i: discord.Interaction):
            await i.response.defer()
            async with self.manager.lock(i.guild_id):
                await self.connect_voice(i)
            await i.followup.send("Conectado.")

        @tree.command(name="leave", description="Detener y desconectar Fodw")
        @app_commands.guild_only()
        async def leave(i: discord.Interaction):
            await i.response.defer()
            async with self.manager.lock(i.guild_id):
                player = self.get_player(i)
                self.manager.invalidate(i.guild_id)
                await player.close()
                self.manager.players.pop(i.guild_id, None)
                panel = self.panels.pop(i.guild_id, None)
                if panel:
                    with suppress(discord.HTTPException):
                        await panel.finish()
            await i.followup.send("Desconectado.")

        # Generate no-argument commands with individual closures, not shared state.
        def simple(name, description, action, message):
            async def command(i: discord.Interaction):
                player = self.get_player(i)
                if name == "stop":
                    self.manager.invalidate(i.guild_id)
                action(player)
                await i.response.send_message(message)
            command.__name__ = name
            tree.add_command(app_commands.guild_only()(app_commands.Command(name=name, description=description, callback=command)))

        simple("pause", "Pausar reproducción", lambda p: p.pause(), "Pausado.")
        simple("resume", "Reanudar reproducción", lambda p: p.resume(), "Reanudado.")
        simple("skip", "Saltar la canción actual", lambda p: p.skip(), "Canción saltada.")
        simple("stop", "Detener y vaciar la cola", lambda p: p.stop(), "Reproducción detenida y cola vaciada.")
        simple("clear", "Vaciar canciones pendientes", lambda p: p.queue.items.clear(), "Cola pendiente vaciada.")
        simple("shuffle", "Mezclar canciones pendientes", lambda p: p.queue.shuffle(), "Cola mezclada.")
        def replay(p):
            track = p.queue.current or (p.queue.history[-1] if p.queue.history else None)
            if not track:
                raise MusicError("Todavía no hay canciones para repetir.")
            p.add([track])
        simple("replay", "Agregar de nuevo la canción actual o la última", replay, "Canción agregada nuevamente al final.")

        @tree.command(name="nowplaying", description="Mostrar canción y progreso actual")
        @app_commands.guild_only()
        async def nowplaying(i: discord.Interaction):
            p = self.get_player(i)
            await i.response.defer(ephemeral=True)
            await self.panels[i.guild_id].refresh(force=True)
            await i.followup.send("Reproductor actualizado.", ephemeral=True)

        @tree.command(name="seek", description="Saltar a segundos o minutos:segundos (45, 1:30)")
        @app_commands.guild_only()
        @app_commands.checks.cooldown(1, 2, key=lambda i: (i.guild_id, i.user.id))
        async def seek(i: discord.Interaction, position: str):
            p = self.get_player(i)
            target = p.seek(parse_position(position))
            await i.response.send_message(f"⏩ Saltando a {duration(target)}", ephemeral=True)

        @tree.command(name="queue", description="Ver cola paginada")
        @app_commands.guild_only()
        async def queue(i: discord.Interaction, page: app_commands.Range[int, 1, 50] = 1):
            p = self.get_player(i)
            start = (page - 1) * 10
            lines = [f"{n}. {discord.utils.escape_markdown(t.title)}" for n, t in enumerate(p.queue.items[start:start + 10], start + 1)]
            await i.response.send_message(embed=discord.Embed(title=f"Cola · página {page}", description="\n".join(lines) or "Sin canciones en esta página.", color=0x7755EE))

        @tree.command(name="remove", description="Quitar una posición de la cola")
        @app_commands.guild_only()
        async def remove(i: discord.Interaction, position: app_commands.Range[int, 1, 500]):
            self.get_player(i).queue.remove(position)
            await i.response.send_message("Canción eliminada.")

        @tree.command(name="move", description="Mover una canción pendiente")
        @app_commands.guild_only()
        async def move(i: discord.Interaction, source: app_commands.Range[int, 1, 500], destination: app_commands.Range[int, 1, 500]):
            self.get_player(i).queue.move(source, destination)
            await i.response.send_message("Posición actualizada.")

        @tree.command(name="loop", description="Repetir canción, cola o desactivar")
        @app_commands.guild_only()
        async def loop(i: discord.Interaction, mode: Loop):
            self.get_player(i).queue.loop = mode
            labels = {Loop.OFF: "Repetición desactivada", Loop.TRACK: "Repetir canción", Loop.QUEUE: "Repetir cola"}
            await i.response.send_message(labels[mode])

        @tree.command(name="volume", description="Volumen de 0 a 100, guardado por servidor")
        @app_commands.guild_only()
        async def volume(i: discord.Interaction, value: app_commands.Range[int, 0, 100]):
            p = self.get_player(i)
            self.repo.save_volume(i.guild_id, value)
            p.set_volume(value)
            await i.response.send_message(f"Volumen: {value}%")

        @tree.command(name="history", description="Últimas canciones de esta sesión, máximo 25")
        @app_commands.guild_only()
        async def history(i: discord.Interaction):
            p = self.get_player(i)
            lines = [discord.utils.escape_markdown(t.title)[:120] for t in reversed(p.queue.history)]
            await i.response.send_message(embed=discord.Embed(title="Historial de sesión", description="\n".join(lines) or "Todavía no hay historial."))
