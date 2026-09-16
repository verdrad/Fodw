from collections import deque
from dataclasses import dataclass
from enum import Enum
import random


class MusicError(Exception):
    """Mensaje seguro que puede mostrarse en Discord."""


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    url: str
    duration: int | None = None
    thumbnail: str | None = None
    requester: int = 0
    source: str = "YouTube"


class Loop(str, Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class Queue:
    def __init__(self, limit=100):
        self.items: list[Track] = []
        self.history: deque[Track] = deque(maxlen=25)
        self.current: Track | None = None
        self.loop = Loop.OFF
        self.limit = limit

    def add(self, tracks):
        tracks = list(tracks)
        if len(self.items) + len(tracks) > self.limit:
            raise MusicError(f"La cola admite hasta {self.limit} canciones pendientes.")
        self.items.extend(tracks)

    def advance(self, reason="finished"):
        old = self.current
        if old:
            self.history.append(old)
            if reason == "finished" and self.loop == Loop.TRACK:
                return old
            if reason == "finished" and self.loop == Loop.QUEUE:
                self.items.append(old)
        self.current = self.items.pop(0) if self.items else None
        return self.current

    def remove(self, position):
        self._check(position)
        return self.items.pop(position - 1)

    def move(self, source, destination):
        self._check(source)
        self._check(destination)
        self.items.insert(destination - 1, self.items.pop(source - 1))

    def _check(self, position):
        if not 1 <= position <= len(self.items):
            raise MusicError("Posición fuera de la cola; las posiciones empiezan en 1.")

    def shuffle(self):
        random.shuffle(self.items)

    def stop(self):
        self.items.clear()
        self.current = None

    def previous(self):
        if not self.history:
            raise MusicError("No hay una canción anterior en el historial.")
        previous = self.history.pop()
        if self.current:
            self.items.insert(0, self.current)
        self.current = previous
        return previous
