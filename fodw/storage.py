from pathlib import Path
import sqlite3


class SettingsRepository:
    """Small bounded records, no credentials, requester IDs or stream URLs."""
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS settings (guild INTEGER PRIMARY KEY, volume INTEGER NOT NULL CHECK(volume BETWEEN 0 AND 100), autoplay INTEGER NOT NULL DEFAULT 0)")
        self.db.commit()

    def volume(self, guild, default):
        row = self.db.execute("SELECT volume FROM settings WHERE guild=?", (guild,)).fetchone()
        return row[0] if row else default

    def save_volume(self, guild, volume):
        if not 0 <= volume <= 100:
            raise ValueError("Volumen fuera de rango")
        with self.db:
            self.db.execute("INSERT INTO settings(guild,volume) VALUES(?,?) ON CONFLICT(guild) DO UPDATE SET volume=excluded.volume", (guild, volume))

    def close(self):
        self.db.close()
