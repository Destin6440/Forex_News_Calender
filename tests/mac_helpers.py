from ff_calendar_toolkit.mac_app.models import Event
def neutral_event(key,name="Event Alpha",currency="Currency A",impact="red",time_et="09:00",raw_time=None,date_et="2025-01-06",source_id=None):
    return Event(key,name,name.lower(),currency,impact,date_et,time_et,raw_time,"fixture",source_id or key)
