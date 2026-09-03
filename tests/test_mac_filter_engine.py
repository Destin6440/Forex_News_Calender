from ff_calendar_toolkit.mac_app.filter_engine import FilterValidationError, search
from ff_calendar_toolkit.mac_app.filter_schema import EventRule, RuleGroup, SearchDefinition
from ff_calendar_toolkit.mac_app.models import Event
import pytest

def event(key,name="Event Alpha",currency="Currency A",impact="red",time="09:00",raw=None,date_et="2025-01-06"):
    return Event(key,name,name.lower(),currency,impact,date_et,time,raw,"fixture",key)
def test_required_optional_excluded_and_exact():
    events=[event("1"),event("2","Event Beta")]
    d=SearchDefinition(root=RuleGroup("AND",[EventRule("a",name="Alpha"),EventRule("b",mode="optional",name="Beta")]),additional_policy="exact")
    assert search(events,d)[0].matched_event_count==2
    d.root.children.append(EventRule("x",mode="excluded",name="Gamma")); assert search(events,d)
def test_nested_or_and_invalid_regex():
    d=SearchDefinition(root=RuleGroup("AND",[RuleGroup("OR",[EventRule("a",name="Alpha"),EventRule("b",name="Beta")])]))
    assert search([event("1")],d)
    d.root=RuleGroup(children=[EventRule(name="[",name_operator="regex")])
    with pytest.raises(FilterValidationError): search([event("1")],d)
def test_clockless_and_stable_ids():
    es=[event("stable-a",time=None,raw="All Day"),event("stable-b",time=None,raw="All Day")]
    d=SearchDefinition(root=RuleGroup(children=[EventRule(time_mode="clockless",minimum=2)]))
    assert len(search(es,d)[0].events)==2

@pytest.mark.parametrize("operator,needle",[("contains","Alpha"),("exact","Event Alpha"),("starts_with","Event"),("ends_with","Alpha"),("regex",r"Alpha$")])
def test_all_name_operators(operator,needle):
    d=SearchDefinition(root=RuleGroup(children=[EventRule(name=needle,name_operator=operator)]))
    assert search([event("1")],d)

def test_optional_and_excluded_do_not_satisfy_or():
    d=SearchDefinition(root=RuleGroup("OR",[EventRule("optional",mode="optional",name="Alpha"),EventRule("required",name="Gamma")]))
    assert search([event("1")],d)==[]
    d.root.children[0].mode="excluded";assert search([event("1")],d)==[]

def test_group_without_required_descendant_rejects():
    d=SearchDefinition(root=RuleGroup(children=[EventRule(mode="optional")]))
    assert search([event("1")],d)==[]

def test_exact_checks_events_outside_global_scope():
    d=SearchDefinition(root=RuleGroup(children=[EventRule(currencies=["Currency A"])]),currencies=["Currency A"],additional_policy="exact")
    assert search([event("1"),event("2",currency="Currency B")],d)==[]

def test_counted_scope_requires_both_configured_dimensions():
    es=[event("1"),event("2",name="Event Beta",currency="Currency B")]
    d=SearchDefinition(root=RuleGroup(children=[EventRule(name="Alpha")]),additional_policy="counted_scope",counted_currencies=["Currency B"],counted_impacts=["red"])
    assert search(es,d)==[]
    d.counted_impacts=[];assert search(es,d)

@pytest.mark.parametrize("field,value",[("additional_policy","bad"),("sort","bad")])
def test_invalid_definition_values(field,value):
    d=SearchDefinition(root=RuleGroup(children=[EventRule()]));setattr(d,field,value)
    with pytest.raises(FilterValidationError):search([event("1")],d)

def test_invalid_bounds_and_time():
    d=SearchDefinition(root=RuleGroup(children=[EventRule(minimum=2,maximum=1,earliest_time="12:00",latest_time="10:00")]))
    with pytest.raises(FilterValidationError):search([event("1")],d)

def test_cancellation_and_sorting():
    from threading import Event
    d=SearchDefinition(root=RuleGroup(children=[EventRule()]));c=Event();c.set();assert search([event("1")],d,c)==[]
    two=event("2",date_et="2025-01-07");assert [x.date_et for x in search([event("1"),two],d)]==["2025-01-07","2025-01-06"]
