"""One editable Discord message per voice session; no audio state lives here."""
import asyncio
import time
from contextlib import suppress
import discord
from .position import progress_bar


def now_embed(player):
    track = player.queue.current
    if not track or player.closed:
        return discord.Embed(title="⏹️ Reproducción detenida", description="La cola está vacía o la sesión terminó.", color=0x7755EE)
    icon = "⏸️" if player.paused_at is not None else "🎵"
    embed = discord.Embed(title=f"{icon} {track.title}"[:256],
        description=discord.utils.escape_markdown(track.artist), url=track.url, color=0x7755EE)
    embed.add_field(name="Progreso", value=progress_bar(player.progress, track.duration), inline=False)
    embed.add_field(name="Solicitado por", value=f"<@{track.requester}>")
    embed.add_field(name="Fuente", value=track.source)
    labels = {"off": "Off", "track": "Canción", "queue": "Cola"}
    embed.set_footer(text=f"🔊 {player.volume}% | 🔁 {labels[player.queue.loop.value]} · Actualiza cada 10 s")
    if track.thumbnail and track.thumbnail.startswith("https://"):
        embed.set_thumbnail(url=track.thumbnail)
    return embed


class NowPlayingPanel:
    def __init__(self, channel, player, make_view, *, move_after=90):
        self.channel, self.player, self.make_view = channel, player, make_view
        self.message = None
        self.view = None
        self.last_payload = None
        self.lock = asyncio.Lock()
        self.move_after = move_after
        self.last_move = 0.0

    async def new_track(self):
        """Start a new panel message for a newly playing track."""
        async with self.lock:
            if self.message:
                with suppress(discord.HTTPException, discord.NotFound):
                    await self.message.delete()
            if self.view:
                self.view.stop()
            self.message = None
            self.view = None
            self.last_payload = None
            self.last_move = time.monotonic()
        await self.refresh(force=True)

    async def _too_old(self):
        if not self.message or not getattr(self.message, "created_at", None):
            return False
        age = (discord.utils.utcnow() - self.message.created_at).total_seconds()
        return age >= self.move_after and time.monotonic() - self.last_move >= self.move_after

    async def refresh(self, *, force=False):
        async with self.lock:
            embed = now_embed(self.player)
            payload = embed.to_dict()
            # Avoid re-posting a deleted panel every tick. /nowplaying can restore it.
            if self.message is None and not force:
                return
            if not force and await self._too_old():
                with suppress(discord.HTTPException, discord.NotFound):
                    await self.message.delete()
                if self.view:
                    self.view.stop()
                self.message = None
                self.view = None
                self.last_payload = None
                self.last_move = time.monotonic()
            if not force and payload == self.last_payload:
                return
            view = self.make_view() if self.player.queue.current and not self.player.closed else None
            try:
                if self.message is None:
                    self.message = await self.channel.send(embed=embed, view=view)
                else:
                    try:
                        await self.message.edit(embed=embed, view=view)
                    except discord.NotFound:
                        self.message = None
                        if not force:
                            if view:
                                view.stop()
                            return
                        self.message = await self.channel.send(embed=embed, view=view)
            except Exception:
                if view:
                    view.stop()
                raise
            if self.view:
                self.view.stop()
            self.view, self.last_payload = view, payload

    async def finish(self):
        try:
            if self.message:
                await self.refresh()
        finally:
            if self.view:
                self.view.stop()
