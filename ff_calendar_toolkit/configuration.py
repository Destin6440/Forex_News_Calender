"""Historical same-day event configuration search."""
from __future__ import annotations

from collections import defaultdict
from .ingest import normalized_name


def find_configurations(rows: list[dict], event: str, currencies: list[str], impacts: list[str], only: bool) -> list[dict]:
    wanted=normalized_name(event); currencies={x.upper() for x in currencies}; impacts={x.lower() for x in impacts}
    by_day=defaultdict(list)
    for row in rows: by_day[row["date_et"]].append(row)
    results=[]
    for day, events in sorted(by_day.items()):
        matching=[e for e in events if e["event_name_normalized"]==wanted and e["currency"] in currencies and e["impact_color"] in impacts]
        if not matching: continue
        counted=[e for e in events if e["currency"] in currencies and e["impact_color"] in impacts]
        ignored=[e for e in events if e["impact_color"] in {"yellow","gray"}]
        extras=[e for e in counted if e not in matching]
        passed=not only or not extras
        results.append({"date":day,"matching_event":[e["event_name"] for e in matching],
          "same_day_counted_events":[f'{e["currency"]} {e["impact_color"]}: {e["event_name"]}' for e in counted],
          "ignored_yellow_gray_events":[f'{e["currency"]} {e["impact_color"]}: {e["event_name"]}' for e in ignored],
          "matched":passed,"explanation":"matched: requested event is the only counted event" if passed and only else
            ("matched: requested event is present" if passed else f"failed: {len(extras)} other counted event(s) occurred")})
    return results
