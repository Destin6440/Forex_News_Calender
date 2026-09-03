import sqlite3
import pytest
from ff_calendar_toolkit.mac_app.database_reader import DatabaseReader,DatabaseError,discover_database

def make_db(path):
    c=sqlite3.connect(path); c.execute("CREATE TABLE events(event_key TEXT,event_name TEXT,event_name_normalized TEXT,currency TEXT,impact_color TEXT,date_et TEXT,time_et TEXT,raw_time TEXT,source_type TEXT,source_event_id TEXT,actual TEXT,forecast TEXT,previous TEXT)"); c.execute("INSERT INTO events VALUES ('1','Event Alpha','event alpha','Currency A','red','2025-01-01',NULL,'Tentative','fixture','a',NULL,NULL,NULL)"); c.commit(); c.close()
def test_read_only_and_metadata(tmp_path):
    p=tmp_path/"x.sqlite"; make_db(p); r=DatabaseReader(p)
    with r.connect() as c:
        assert c.execute("PRAGMA query_only").fetchone()[0]==1
        with pytest.raises(sqlite3.OperationalError): c.execute("DELETE FROM events")
    assert r.metadata()["count"]==1
def test_discovery_and_errors(tmp_path,monkeypatch):
    p=tmp_path/"x.sqlite"; make_db(p); monkeypatch.setenv("FF_CALENDAR_DB",str(p)); assert discover_database()==p.resolve()
    with pytest.raises(DatabaseError): DatabaseReader(tmp_path/"missing")

def test_special_character_path_and_facets(tmp_path):
    p=tmp_path/"space # ü.sqlite";make_db(p);r=DatabaseReader(p)
    assert r.facets()["events"]==["Event Alpha"]
    assert r.events()[0].event_key=="1"

def test_last_selected_precedes_environment(tmp_path,monkeypatch):
    first=tmp_path/"first.sqlite";second=tmp_path/"second.sqlite";make_db(first);make_db(second);monkeypatch.setenv("FF_CALENDAR_DB",str(second))
    assert discover_database(first)==first.resolve()
