from ff_calendar_toolkit.mac_app.saved_searches import SavedSearchStore
from ff_calendar_toolkit.mac_app.filter_schema import SearchDefinition
def test_roundtrip_and_malformed_recovery(tmp_path):
    s=SavedSearchStore(tmp_path); s.save(SearchDefinition(name="Neutral")); assert s.load()["Neutral"].name=="Neutral"
    s.path.write_text("bad"); assert s.load()=={}; assert s.warning
def test_crud(tmp_path):
    s=SavedSearchStore(tmp_path);s.save(SearchDefinition(name="Alpha"));s.save(SearchDefinition(name="Beta"));assert set(s.load())=={"Alpha","Beta"};s.delete("Alpha");assert set(s.load())=={"Beta"}
