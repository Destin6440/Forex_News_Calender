from __future__ import annotations
import json, shutil
from datetime import datetime, timezone
from pathlib import Path
from .filter_schema import SearchDefinition, from_dict

class SavedSearchStore:
    def __init__(self,directory): self.directory=Path(directory); self.path=self.directory/"saved-searches.json"; self.warning=None
    def load(self):
        if not self.path.exists(): return {}
        try:
            raw=json.loads(self.path.read_text()); return {k:from_dict(v) for k,v in raw.items()}
        except Exception as exc:
            self.directory.mkdir(parents=True,exist_ok=True); backup=self.path.with_name(f"saved-searches.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"); shutil.move(self.path,backup); self.warning=f"Damaged saved searches were preserved at {backup}: {exc}"; return {}
    def write(self,searches):
        self.directory.mkdir(parents=True,exist_ok=True); temp=self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({k:v.to_dict() for k,v in searches.items()},indent=2,sort_keys=True)); temp.replace(self.path)
    def save(self,definition):
        searches=self.load(); searches[definition.name]=definition; self.write(searches)
    def delete(self,name): searches=self.load(); searches.pop(name,None); self.write(searches)
