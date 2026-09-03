"""Versioned JSON filter contract. Empty children intentionally means no results."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

@dataclass
class EventRule:
    id: str = "rule-1"; label: str = ""; mode: str = "required"
    currencies: list[str] = field(default_factory=list); impacts: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list); name: str = ""; name_operator: str = "contains"
    earliest_time: str | None = None; latest_time: str | None = None; time_mode: str = "any"
    raw_time: str = ""; minimum: int = 1; maximum: int | None = None

@dataclass
class RuleGroup:
    operator: str = "AND"; children: list[Any] = field(default_factory=list); id: str = "root"

@dataclass
class SearchDefinition:
    schema_version: int = SCHEMA_VERSION; name: str = "Untitled Search"
    root: RuleGroup = field(default_factory=RuleGroup); start_date: str | None = None; end_date: str | None = None
    weekdays: list[int] = field(default_factory=lambda: list(range(7)))
    currencies: list[str] = field(default_factory=list); impacts: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list); minimum_events: int = 0; maximum_events: int | None = None
    sort: str = "newest"; additional_policy: str = "allow"
    counted_currencies: list[str] = field(default_factory=list); counted_impacts: list[str] = field(default_factory=list)

    def to_dict(self): return asdict(self)

def _node(value):
    if "children" in value: return RuleGroup(value.get("operator", "AND"), [_node(x) for x in value["children"]], value.get("id", "root"))
    allowed = EventRule.__dataclass_fields__
    return EventRule(**{k: v for k, v in value.items() if k in allowed})

def from_dict(value: dict) -> SearchDefinition:
    version = value.get("schema_version")
    if version != SCHEMA_VERSION: raise ValueError(f"Unsupported filter schema version: {version}")
    fields = SearchDefinition.__dataclass_fields__
    data = {k: v for k, v in value.items() if k in fields and k != "root"}
    data["root"] = _node(value.get("root", {"operator":"AND", "children":[]}))
    return SearchDefinition(**data)
