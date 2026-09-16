"""Position, parsing and rendering independent of Discord and FFmpeg."""
import re
import time
from .queue import MusicError


def parse_position(value: str) -> int:
    value = value.strip()
    if re.fullmatch(r"[0-9]{1,8}", value):
        return int(value)
    match = re.fullmatch(r"([0-9]{1,6}):([0-5][0-9])", value)
    if match:
        return int(match[1]) * 60 + int(match[2])
    raise MusicError("Posición inválida. Usá segundos (45) o minutos:segundos (1:30), sin negativos.")


def duration(seconds):
    if seconds is None:
        return "Desconocida / en vivo"
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02}"


def progress_bar(position, total, width=20):
    if not total or total <= 0:
        return f"{duration(position)} · Duración desconocida / en vivo"
    position = max(0, min(position, total))
    point = min(width - 1, int(position / total * (width - 1)))
    bar = "━" * point + "●" + "━" * (width - point - 1)
    return f"{duration(position)} {bar} {duration(total)}"


class PlaybackPosition:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.reset()

    def reset(self, offset=0, paused=False):
        self.offset = float(offset)
        self.anchor = self.clock()
        self.paused_at = self.anchor if paused else None
        self.running = False

    def start(self, offset=0, paused=False):
        self.reset(offset, paused)
        self.running = True

    @property
    def seconds(self):
        end = self.paused_at if self.paused_at is not None else self.clock()
        return max(0, self.offset + (end - self.anchor if self.running else 0))

    def pause(self):
        if self.paused_at is None:
            self.paused_at = self.clock()

    def resume(self):
        if self.paused_at is not None:
            self.anchor += self.clock() - self.paused_at
            self.paused_at = None
