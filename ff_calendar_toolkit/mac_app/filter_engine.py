"""Deterministic, UI-independent evaluation of calendar search definitions."""
from __future__ import annotations
import re
from collections import defaultdict
from datetime import date, time
from threading import Event as CancelEvent
from .filter_schema import EventRule, RuleGroup, SearchDefinition
from .models import DateResult

class FilterValidationError(ValueError): pass
VALID_MODES={"required","optional","excluded"}; VALID_NAMES={"contains","exact","starts_with","ends_with","regex"}
VALID_TIMES={"any","timed","clockless"}; VALID_POLICIES={"allow","counted_scope","exact"}

def normalize_name(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())

def validate(definition: SearchDefinition) -> list[str]:
    errors=[]
    if definition.additional_policy not in VALID_POLICIES: errors.append("Unsupported additional-event policy")
    if definition.sort not in {"newest","oldest"}: errors.append("Unsupported sort order")
    try:
        start=date.fromisoformat(definition.start_date) if definition.start_date else None
        end=date.fromisoformat(definition.end_date) if definition.end_date else None
        if start and end and start>end: errors.append("Start date must not follow end date")
    except ValueError: errors.append("Dates must use YYYY-MM-DD")
    if definition.minimum_events<0 or definition.maximum_events is not None and definition.maximum_events<definition.minimum_events: errors.append("Invalid total-event bounds")
    if not set(definition.weekdays)<=set(range(7)): errors.append("Weekdays must be between 0 and 6")
    def walk(n):
        if isinstance(n,RuleGroup):
            if n.operator not in {"AND","OR"}: errors.append("Group operator must be AND or OR")
            for c in n.children: walk(c)
            return
        if not isinstance(n,EventRule): errors.append("Unknown rule node"); return
        if n.mode not in VALID_MODES: errors.append(f"{n.id}: unsupported rule mode")
        if n.name_operator not in VALID_NAMES: errors.append(f"{n.id}: unsupported name operator")
        if n.time_mode not in VALID_TIMES: errors.append(f"{n.id}: unsupported time mode")
        if n.minimum<0 or n.maximum is not None and n.maximum<n.minimum: errors.append(f"{n.id}: invalid occurrence bounds")
        try:
            early=time.fromisoformat(n.earliest_time) if n.earliest_time else None; late=time.fromisoformat(n.latest_time) if n.latest_time else None
            if early and late and early>late: errors.append(f"{n.id}: earliest time must not follow latest time")
        except ValueError: errors.append(f"{n.id}: times must use HH:MM")
        if n.name_operator=="regex":
            try: re.compile(n.name,re.IGNORECASE)
            except re.error as exc: errors.append(f"{n.label or n.id}: invalid regular expression: {exc}")
    walk(definition.root); return errors

def _event_match(e,r):
    if r.currencies and e.currency not in r.currencies or r.impacts and e.impact_color not in r.impacts or r.source_types and e.source_type not in r.source_types:return False
    timed=bool(e.time_et)
    if r.time_mode=="timed" and not timed or r.time_mode=="clockless" and timed:return False
    if timed and (r.earliest_time and e.time_et<r.earliest_time or r.latest_time and e.time_et>r.latest_time):return False
    if r.raw_time and normalize_name(r.raw_time) not in normalize_name(e.raw_time or ""):return False
    if not r.name:return True
    if r.name_operator=="regex":return bool(re.search(r.name,e.event_name,re.I))
    needle=normalize_name(r.name); value=normalize_name(e.event_name_normalized or e.event_name)
    return {"contains":needle in value,"exact":needle==value,"starts_with":value.startswith(needle),"ends_with":value.endswith(needle)}[r.name_operator]

def _rules(n): return [n] if isinstance(n,EventRule) else [r for c in n.children for r in _rules(c)]

def search(events,definition,cancel:CancelEvent|None=None):
    errors=validate(definition)
    if errors:raise FilterValidationError("; ".join(errors))
    if not definition.root.children:return []
    grouped=defaultdict(list)
    for e in events:grouped[e.date_et].append(e)
    output=[]
    for day,items in grouped.items():
        if cancel and cancel.is_set():return []
        d=date.fromisoformat(day)
        if definition.start_date and day<definition.start_date or definition.end_date and day>definition.end_date or d.weekday() not in definition.weekdays:continue
        globally_scoped=[e for e in items if (not definition.currencies or e.currency in definition.currencies) and (not definition.impacts or e.impact_color in definition.impacts) and (not definition.source_types or e.source_type in definition.source_types)]
        if len(globally_scoped)<definition.minimum_events or definition.maximum_events is not None and len(globally_scoped)>definition.maximum_events:continue
        matches={}; excluded=False
        def evaluate(n):
            nonlocal excluded
            if isinstance(n,EventRule):
                found=[e.event_key for e in globally_scoped if _event_match(e,n)]; matches[n.id]=found
                if n.mode=="excluded" and found:excluded=True
                if n.mode!="required":return None
                return len(found)>=n.minimum and (n.maximum is None or len(found)<=n.maximum)
            eligible=[v for c in n.children if (v:=evaluate(c)) is not None]
            if not eligible:return None
            return all(eligible) if n.operator=="AND" else any(eligible)
        decision=evaluate(definition.root)
        if excluded or decision is not True:continue
        accepted={key for r in _rules(definition.root) if r.mode!="excluded" for key in matches.get(r.id,[])}
        if definition.additional_policy=="exact" and any(e.event_key not in accepted for e in items):continue
        if definition.additional_policy=="counted_scope":
            def counted(e):return bool(definition.counted_currencies and e.currency in definition.counted_currencies) and bool(definition.counted_impacts and e.impact_color in definition.counted_impacts)
            if any(counted(e) and e.event_key not in accepted for e in items):continue
        output.append(DateResult(day,list(items),matches))
    return sorted(output,key=lambda r:r.date_et,reverse=definition.sort=="newest")
