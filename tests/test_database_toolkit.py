import csv
from datetime import datetime
from pathlib import Path

import pytest

from ff_calendar_toolkit.configuration import find_configurations
from ff_calendar_toolkit.database import CalendarDatabase
from ff_calendar_toolkit.ingest import SourceError, canonical, impact, parse_archive, parse_html
from ff_calendar_toolkit.pipeline import validate


def raw(day="2024-03-10", clock="1:30pm", event="Employment Change", impact_value="red", **kw):
    return {"date":day,"time":clock,"currency":"USD","event":event,"impact":impact_value,**kw}


def test_exact_impact_mapping():
    assert [impact(x) for x in ("red","orange","yellow","gray")]==[("red","High"),("orange","Medium"),("yellow","Low"),("gray","Non-Economic/Holiday")]
    with pytest.raises(SourceError): impact("purple")


def test_archive_import_idempotency_and_revision(tmp_path):
    content=b"date,time,currency,impact,event,actual,forecast,previous\n2024-01-01,8:30am,USD,red,Jobs,1,2,3\n"
    rows=parse_archive(content); db=CalendarDatabase(tmp_path/"db.sqlite")
    db.upsert(rows); first=db.rows()[0]["first_seen_at"]
    db.upsert(rows); assert len(db.rows())==1
    revised=canonical(raw(day="2024-01-01",clock="8:30am",event="Jobs",actual="9",source_event_id="42"),"test")
    db.upsert([revised]); revised["actual"]="10"; revised["time"]="9:00am"; db.upsert([revised])
    assert len(db.rows())==2 and next(r for r in db.rows() if r["source_event_id"]=="42")["actual"]=="10"


HTML='''<table><tr class="calendar__row"><td class="calendar__date">WedAug 2</td><td class="calendar__time">8:15am</td><td class="calendar__currency">USD</td><td class="calendar__impact"><span class="icon--ff-impact-red"></span></td><td class="calendar__event"><a href="/calendar/1">ADP Non-Farm Employment Change</a></td></tr><tr class="calendar__row"><td class="calendar__time"></td><td class="calendar__currency">EUR</td><td class="calendar__impact icon--ff-impact-orange"></td><td class="calendar__event">Simultaneous Event</td></tr><tr class="calendar__row"><td class="calendar__date">ThuAug 3</td><td class="calendar__time">All Day</td><td class="calendar__currency">ALL</td><td class="calendar__impact icon--ff-impact-gray"></td><td class="calendar__event">Holiday</td></tr></table>'''


def test_html_time_propagation_simultaneous_and_all_day():
    rows=parse_html(HTML,"https://www.forexfactory.com/calendar","2023-08")
    assert rows[0]["time_et"]==rows[1]["time_et"]=="08:15"
    assert rows[2]["all_day"] and rows[2]["time_et"] is None


def test_verification_and_empty_pages_rejected():
    for page in ("<title>Verify you are human</title>","<html>nothing</html>"):
        with pytest.raises(SourceError): parse_html(page)


def test_month_year_boundaries_and_dst_conversion():
    dec=canonical(raw(day="2023-12-31",clock="11:30pm"),"test")
    jan=canonical(raw(day="2024-01-01",clock="12:30am"),"test")
    winter=canonical(raw(day="2024-01-10",clock="8:30am"),"test")
    summer=canonical(raw(day="2024-07-10",clock="8:30am"),"test")
    assert dec["date_et"] < jan["date_et"]
    assert datetime.fromisoformat(winter["datetime_utc"]).hour==13
    assert datetime.fromisoformat(summer["datetime_utc"]).hour==12


def test_configuration_matching_not_hardcoded():
    rows=[]
    for day, extras in (("2023-08-02",[]),("2023-12-06",[]),("2024-05-01",["ISM Manufacturing PMI"])):
        rows.append(canonical(raw(day=day,event="ADP Non-Farm Employment Change",impact_value="orange"),"test"))
        rows += [canonical(raw(day=day,event=e,impact_value="red"),"test") for e in extras]
        rows.append(canonical(raw(day=day,event="Minor",impact_value="yellow"),"test"))
    result=find_configurations(rows,"ADP Non-Farm Employment Change",["USD","EUR"],["red","orange"],True)
    assert [x["matched"] for x in result]==[True,True,False]


def test_deterministic_csv_and_duplicate_validation(tmp_path):
    db=CalendarDatabase(tmp_path/"db.sqlite"); db.upsert([canonical(raw(),"test")])
    db.export(["csv"],tmp_path/"a"); db.export(["csv"],tmp_path/"b")
    assert (tmp_path/"a/forex_factory_calendar_full.csv").read_bytes()==(tmp_path/"b/forex_factory_calendar_full.csv").read_bytes()
    manifest,errors=validate(db); assert manifest["duplicate_count"]==0


def test_incomplete_period_is_retained_for_retry(tmp_path):
    db=CalendarDatabase(tmp_path/"db.sqlite"); db.mark_period("2025-05","incomplete",error="blocked")
    assert db.connection.execute("SELECT status FROM periods WHERE period='2025-05'").fetchone()[0]=="incomplete"
