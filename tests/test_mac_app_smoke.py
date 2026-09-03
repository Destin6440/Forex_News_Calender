import os
from pathlib import Path
from threading import Event
import pytest
import sqlite3
from contextlib import contextmanager
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["QT_QUICK_CONTROLS_STYLE"]="Basic"
os.environ["QT_QUICK_BACKEND"]="software"
PySide6=pytest.importorskip("PySide6")
from PySide6.QtCore import QMetaObject,QObject,QThread,Qt,qInstallMessageHandler
from PySide6.QtWidgets import QApplication,QMessageBox
from ff_calendar_toolkit.mac_app.controller import AppController
from ff_calendar_toolkit.mac_app.qml_runtime import create_engine,destroy_engine
from PySide6.QtTest import QSignalSpy

def wait_for_signal(spy,controller,timeout=3000):
    """Wait unless a very fast background operation already emitted."""
    if spy.count()>0 or spy.wait(timeout):return
    pytest.fail(f"Search timed out after {timeout} ms: {controller.searchDiagnostics()!r}")

@contextmanager
def qml_scene(controller):
    """Keep QML message capture active until the object tree is gone."""
    messages=[]
    def capture_message(kind,context,message):
        location=f"{context.file}:{context.line}: " if context.file else ""
        messages.append(f"{location}{message}")
    previous=qInstallMessageHandler(capture_message)
    engine=root=None
    try:
        try:
            engine,root=create_engine(controller)
        except Exception as error:
            pytest.fail(f"QML engine creation failed: {error!r}; captured Qt messages: {messages!r}")
        yield engine,root
    finally:
        try:
            if engine is not None:destroy_engine(engine)
        finally:
            try:
                controller.shutdown()
                QApplication.instance().processEvents()
            finally:
                qInstallMessageHandler(previous)
    qml_directory=str(Path(__file__).parents[1]/"ff_calendar_toolkit"/"mac_app"/"qml").replace("\\","/")+"/"
    bad=[m for m in messages if qml_directory in m.replace("\\","/") or "controller is null" in m or "QThread: Destroyed" in m or "shortcut" in m.lower()]
    assert not bad, f"QML loading/teardown warnings: {bad!r}"

def make_database(path):
    connection=sqlite3.connect(path)
    connection.execute("CREATE TABLE events(event_key TEXT,event_name TEXT,event_name_normalized TEXT,currency TEXT,impact_color TEXT,date_et TEXT,time_et TEXT,raw_time TEXT,source_type TEXT,source_event_id TEXT,actual TEXT,forecast TEXT,previous TEXT)")
    connection.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",[("a","Event Alpha","event alpha","Currency A","red","2025-01-06","09:00",None,"fixture","a",None,None,None),("b","Event Beta","event beta","Currency B","orange","2025-01-06","10:00",None,"fixture","b",None,None,None)])
    connection.commit();connection.close()

def test_real_qml_engine_loads_with_required_context(tmp_path):
    app=QApplication.instance() or QApplication([]);controller=AppController(tmp_path)
    with qml_scene(controller) as (engine,root):
        app.processEvents()
        assert root.isVisible()

def test_controller_rule_and_saved_search_actions(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"))
    c=AppController(tmp_path);c.addRule();assert c.ruleModel.count==1;ident=c.ruleModel.items[0]["ruleId"];c.updateRule(ident,"name","Event Alpha");c.setSearchName("Neutral");c.saveSearch();assert c.savedSearchModel.count==1;c.newSearch();c.loadSearch("Neutral");assert c.ruleModel.count==1;c.shutdown()

def test_controller_exact_search_uses_complete_date_and_state_sync(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));database=tmp_path/"calendar.sqlite";make_database(database)
    c=AppController(tmp_path);assert c.open_database(str(database));assert c.currencies==["Currency A","Currency B"] and "2 events" in c.databaseSummary
    c.addRule();rule=c.ruleModel.items[0]["ruleId"];c.updateRule(rule,"currencies","Currency A");c.setGlobal("currencies","Currency A");c.setPolicy("Exact event set")
    completion_threads=[];c.searchFinished.connect(lambda:completion_threads.append(QThread.currentThread()))
    spy=QSignalSpy(c.searchFinished);c.runSearch();wait_for_signal(spy,c);assert c.resultCount==0 and c.resultsCurrent
    assert completion_threads[-1]==c.thread() and c.thread()==app.thread()
    c.setPolicy("Allow additional events");assert not c.resultsCurrent;spy=QSignalSpy(c.searchFinished);c.runSearch();wait_for_signal(spy,c);assert c.resultCount==1
    c.setSearchName("Alpha");c.saveSearch();c.newSearch();assert c.searchName=="Untitled Search";c.loadSearch("Alpha");assert c.searchName=="Alpha" and c.globalCurrencies=="Currency A"
    c.setGlobal("impacts","red");assert not c.resultsCurrent and c.resultCount==0;c.shutdown()

def test_three_level_group_editing_and_serialization(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));c=AppController(tmp_path)
    c.addGroup();outer=c.ruleModel.items[0]["ruleId"];c.updateGroup(outer,"OR");c.addGroupToGroup(outer);inner=next(x["ruleId"] for x in c.ruleModel.items if x["groupOperator"]=="AND");c.addRuleToGroup(inner)
    assert max(x["depth"] for x in c.ruleModel.items)>=2
    payload=c.definition.to_dict();assert payload["root"]["children"][0]["operator"]=="OR" and payload["root"]["children"][0]["children"][-1]["operator"]=="AND";c.shutdown()

def test_saved_name_validation_collisions_and_qml_state(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));c=AppController(tmp_path)
    errors=[];c.error.connect(errors.append);assert not c.saveSearchAs("   ") and errors
    assert c.saveSearchAs("Alpha") and c.searchName=="Alpha"
    c.newSearch();assert c.saveSearchAs("Beta")
    monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QMessageBox.question",lambda *args:QMessageBox.No)
    assert not c.saveSearchAs("Alpha");assert not c.renameSearch("Beta","Alpha");assert not c.duplicateSearch("Beta","Alpha")
    with qml_scene(c) as (engine,root):
        c.loadSearch("Alpha");app.processEvents();field=root.findChild(QObject,"searchNameField");assert field is not None and field.property("text")=="Alpha"

def test_oldest_saved_search_executes_oldest_first(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));database=tmp_path/"calendar.sqlite";make_database(database)
    connection=sqlite3.connect(database);connection.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",("c","Event Alpha","event alpha","Currency A","red","2025-01-07","09:00",None,"fixture","c",None,None,None));connection.commit();connection.close()
    c=AppController(tmp_path);c.open_database(str(database));c.addRule();c.setSort("Oldest first");c.saveSearchAs("Oldest");c.newSearch();c.loadSearch("Oldest");assert c.resultSort=="oldest"
    spy=QSignalSpy(c.searchFinished);c.runSearch();wait_for_signal(spy,c);assert [item["date"] for item in c.resultModel.items]==["2025-01-06","2025-01-07"];c.shutdown()

def test_stale_cancelled_search_cannot_replace_newer_results(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));database=tmp_path/"calendar.sqlite";make_database(database)
    c=AppController(tmp_path);c.open_database(str(database));c.addRule()
    original=c._search_worker;old_started=Event();release_old=Event()
    def controlled_worker(path,definition,cancel):
        if definition.name=="Old search":
            old_started.set();release_old.wait(3)
        return original(path,definition,cancel)
    monkeypatch.setattr(c,"_search_worker",controlled_worker)
    c.setSearchName("Old search");c.runSearch();assert old_started.wait(1)
    c.setSearchName("New search");spy=QSignalSpy(c.searchFinished);c.runSearch();wait_for_signal(spy,c)
    assert c.resultsCurrent and c.resultCount==1
    published=list(c.resultModel.items);release_old.set()
    # Release the old worker and wait through the controller's deterministic
    # QThread shutdown, then process its queued stale completion.
    c.shutdown();app.processEvents()
    assert list(c.resultModel.items)==published and spy.count()==1

def test_event_name_combo_accepts_typed_and_suggested_values(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));database=tmp_path/"calendar.sqlite";make_database(database);c=AppController(tmp_path);c.open_database(str(database));c.addRule()
    with qml_scene(c) as (engine,root):
        app.processEvents();rule_list=root.findChild(QObject,"ruleList");assert rule_list is not None
        force_layout=getattr(rule_list,"forceLayout",None)
        if callable(force_layout):force_layout()
        else:assert QMetaObject.invokeMethod(rule_list,"forceLayout",Qt.DirectConnection)
        delegate=rule_list.property("currentItem")
        assert delegate is not None
        combo=delegate.findChild(QObject,"eventNameCombo");assert combo is not None
        combo.setProperty("editText","Event Gamma");combo.accepted.emit();app.processEvents();assert c.definition.root.children[0].name=="Event Gamma"
        if callable(force_layout):force_layout()
        else:assert QMetaObject.invokeMethod(rule_list,"forceLayout",Qt.DirectConnection)
        delegate=rule_list.property("currentItem");combo=delegate.findChild(QObject,"eventNameCombo")
        combo.setProperty("currentIndex",0);combo.activated.emit(0);app.processEvents();assert c.definition.root.children[0].name in c.eventNames
