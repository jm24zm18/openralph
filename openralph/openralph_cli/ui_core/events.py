from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass
class UIEvent:
    severity: str
    source: str
    message: str
    at: float


class EventBuffer:
    def __init__(self, max_events: int = 100) -> None:
        self.max_events = max_events
        self._items: list[UIEvent] = []

    def add(self, severity: str, source: str, message: str) -> None:
        self._items.append(UIEvent(severity=severity, source=source, message=message, at=monotonic()))
        if len(self._items) > self.max_events:
            self._items = self._items[-self.max_events :]

    def latest(self, count: int = 8) -> list[UIEvent]:
        if count <= 0:
            return []
        return self._items[-count:]
