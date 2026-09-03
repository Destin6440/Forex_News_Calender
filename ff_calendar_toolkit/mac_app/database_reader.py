"""Strictly read-only SQLite access for the desktop app."""
from __future__ import annotations
import os, sqlite3
from contextlib import closing
from pathlib import Path
from .models import Event

REQUIRED={"event_key","event_name","event_name_normalized","currency","impact_color","date_et","time_et","raw_time","source_type","source_event_id"}

class DatabaseError(RuntimeError): pass
class DatabaseReader:
    def __init__(self,path): self.path=Path(path).expanduser().resolve(); self._metadata=None; self.validate()
    def connect(self):
        if not self.path.is_file(): raise DatabaseError(f"Database not found: {self.path}")
        con=sqlite3.connect(f"{self.path.as_uri()}?mode=ro",uri=True)
        con.row_factory=sqlite3.Row; con.execute("PRAGMA query_only = ON"); return con
    def validate(self):
        try:
            with closing(self.connect()) as c:
                cols={x[1] for x in c.execute("PRAGMA table_info(events)")}
                if not REQUIRED <= cols: raise DatabaseError("Incompatible database: required events columns are missing")
                c.execute("SELECT event_key FROM events LIMIT 1").fetchone()
        except sqlite3.Error as exc: raise DatabaseError(f"Cannot read database: {exc}") from exc
    def metadata(self,refresh=False):
        if self._metadata is None or refresh:
            with closing(self.connect()) as c: lo,hi,n=c.execute("SELECT MIN(date_et),MAX(date_et),COUNT(*) FROM events").fetchone()
            self._metadata={"path":str(self.path),"filename":self.path.name,"modified":self.path.stat().st_mtime,"earliest":lo,"latest":hi,"count":n,"status":"Connected"}
        return dict(self._metadata)
    def facets(self):
        with closing(self.connect()) as c:
            return {k:[r[0] for r in c.execute(f"SELECT DISTINCT {col} FROM events WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}")] for k,col in (("currencies","currency"),("events","event_name"),("impacts","impact_color"),("sources","source_type"))}
    def events(self,start=None,end=None,currencies=(),impacts=(),sources=()):
        where=[]; params=[]
        def add(column,values):
            if values: where.append(f"{column} IN ({','.join('?' for _ in values)})"); params.extend(values)
        if start: where.append("date_et>=?"); params.append(start)
        if end: where.append("date_et<=?"); params.append(end)
        add("currency",currencies); add("impact_color",impacts); add("source_type",sources)
        cols="event_key,event_name,event_name_normalized,currency,impact_color,date_et,time_et,raw_time,source_type,source_event_id,actual,forecast,previous"
        sql=f"SELECT {cols} FROM events"+(" WHERE "+" AND ".join(where) if where else "")+" ORDER BY date_et,event_key"
        with closing(self.connect()) as c: return [Event(**dict(r)) for r in c.execute(sql,params)]

def discover_database(last_selected=None,repo_root=None):
    candidates=[last_selected,os.environ.get("FF_CALENDAR_DB"),Path(repo_root or Path.cwd())/"data/forex_factory.sqlite",Path.home()/"Forex_News_Calender/data/forex_factory.sqlite"]
    for p in candidates:
        if not p: continue
        try: return DatabaseReader(p).path
        except DatabaseError: pass
    return None
