from dataclasses import dataclass
import os
import shutil


def integer(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} debe ser un entero.") from None
    if not low <= value <= high:
        raise ValueError(f"{name} debe estar entre {low} y {high}.")
    return value


@dataclass(frozen=True)
class Config:
    token: str
    ffmpeg: str
    database: str
    volume: int
    idle: int
    empty: int
    max_queue: int
    youtube: bool
    spotify_id: str
    spotify_secret: str
    dev_guild: int | None

    @classmethod
    def load(cls):
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("Falta DISCORD_TOKEN en .env.")
        ffmpeg = shutil.which(os.getenv("FFMPEG_PATH", "ffmpeg"))
        if not ffmpeg:
            raise ValueError("FFmpeg no encontrado. Instalalo y agregalo al PATH o configurá FFMPEG_PATH.")
        guild = os.getenv("DEV_GUILD_ID", "").strip()
        if guild and (not guild.isdigit() or int(guild) <= 0):
            raise ValueError("DEV_GUILD_ID debe ser un ID numérico positivo.")
        return cls(token, ffmpeg, os.getenv("DATABASE_PATH", "data/fodw.sqlite3"),
                   integer("DEFAULT_VOLUME", 50, 0, 100), integer("IDLE_TIMEOUT", 180, 10, 3600),
                   integer("EMPTY_TIMEOUT", 60, 10, 3600), integer("MAX_QUEUE", 100, 1, 500),
                   os.getenv("YOUTUBE_ENABLED", "false").lower() == "true",
                   os.getenv("SPOTIFY_CLIENT_ID", ""), os.getenv("SPOTIFY_CLIENT_SECRET", ""),
                   int(guild) if guild else None)
