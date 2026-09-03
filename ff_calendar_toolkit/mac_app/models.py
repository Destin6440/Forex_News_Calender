from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class Event:
    event_key: str; event_name: str; event_name_normalized: str; currency: str
    impact_color: str; date_et: str; time_et: str | None = None
    raw_time: str | None = None; source_type: str = ""; source_event_id: str | None = None
    actual: str | None = None; forecast: str | None = None; previous: str | None = None

@dataclass
class DateResult:
    date_et: str
    events: list[Event]
    matches: dict[str, list[str]] = field(default_factory=dict)

    @property
    def matched_event_count(self): return len({k for keys in self.matches.values() for k in keys})
