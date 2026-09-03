import os
from pathlib import Path
from threading import Event
import pytest
import sqlite3
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["QT_QUICK_CONTROLS_STYLE"]="Basic"
os.environ["QT_QUICK_BACKEND"]="software"
PySide6=pytest.importorskip("PySide6")
from PySide6.QtCore import QObject,QThread,QUrl,qInstallMessageHandler
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtQml import QQmlApplicationEngine
from ff_calendar_toolkit.mac_app.controller import AppController
from PySide6.QtTest import QSignalSpy

def wait_for_signal(spy,timeout=3000):
    """Wait unless a very fast background operation already emitted."""
    return spy.count()>0 or spy.wait(timeout)

def make_database(path):
    connection=sqlite3.connect(path)
    connection.execute("CREATE TABLE events(event_key TEXT,event_name TEXT,event_name_normalized TEXT,currency TEXT,impact_color TEXT,date_et TEXT,time_et TEXT,raw_time TEXT,source_type TEXT,source_event_id TEXT,actual TEXT,forecast TEXT,previous TEXT)")
    connection.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",[("a","Event Alpha","event alpha","Currency A","red","2025-01-06","09:00",None,"fixture","a",None,None,None),("b","Event Beta","event beta","Currency B","orange","2025-01-06","10:00",None,"fixture","b",None,None,None)])
    connection.commit();connection.close()

def test_real_qml_engine_loads_with_required_context(tmp_path):
    app=QApplication.instance() or QApplication([]);controller=AppController(tmp_path)
    engine=QQmlApplicationEngine();context=engine.rootContext()
    for name,value in {"controller":controller,"ruleModel":controller.ruleModel,"resultModel":controller.resultModel,"eventModel":controller.eventModel,"savedSearchModel":controller.savedSearchModel}.items():context.setContextProperty(name,value)
    messages=[];previous=qInstallMessageHandler(lambda kind,context,message:messages.append(message))
    try:
        qml=Path(__file__).parents[1]/"ff_calendar_toolkit/mac_app/qml/Main.qml";engine.load(QUrl.fromLocalFile(str(qml)))
        app.processEvents()
    finally:qInstallMessageHandler(previous)
    roots=engine.rootObjects()
    assert roots, f"QML engine did not create a root object. Qt messages: {messages!r}"
    assert roots[0].isVisible()
    assert not [message for message in messages if "Main.qml" in message]
    controller.shutdown()

def test_controller_rule_and_saved_search_actions(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"))
    c=AppController(tmp_path);c.addRule();assert c.ruleModel.count==1;ident=c.ruleModel.items[0]["ruleId"];c.updateRule(ident,"name","Event Alpha");c.setSearchName("Neutral");c.saveSearch();assert c.savedSearchModel.count==1;c.newSearch();c.loadSearch("Neutral");assert c.ruleModel.count==1;c.shutdown()

def test_controller_exact_search_uses_complete_date_and_state_sync(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));database=tmp_path/"calendar.sqlite";make_database(database)
    c=AppController(tmp_path);assert c.open_database(str(database));assert c.currencies==["Currency A","Currency B"] and "2 events" in c.databaseSummary
    c.addRule();rule=c.ruleModel.items[0]["ruleId"];c.updateRule(rule,"currencies","Currency A");c.setGlobal("currencies","Currency A");c.setPolicy("Exact event set")
    completion_threads=[];c.searchFinished.connect(lambda:completion_threads.append(QThread.currentThread()))
    spy=QSignalSpy(c.searchFinished);c.runSearch();assert wait_for_signal(spy);assert c.resultCount==0 and c.resultsCurrent
    assert completion_threads[-1]==c.thread() and c.thread()==app.thread()
    c.setPolicy("Allow additional events");assert not c.resultsCurrent;spy=QSignalSpy(c.searchFinished);c.runSearch();assert wait_for_signal(spy);assert c.resultCount==1
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
    engine=QQmlApplicationEngine();context=engine.rootContext()
    for name,value in {"controller":c,"ruleModel":c.ruleModel,"resultModel":c.resultModel,"eventModel":c.eventModel,"savedSearchModel":c.savedSearchModel}.items():context.setContextProperty(name,value)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1]/"ff_calendar_toolkit/mac_app/qml/Main.qml")));root=engine.rootObjects()[0]
    c.loadSearch("Alpha");app.processEvents();field=root.findChild(QObject,"searchNameField");assert field is not None and field.property("text")=="Alpha";c.shutdown()

def test_oldest_saved_search_executes_oldest_first(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));database=tmp_path/"calendar.sqlite";make_database(database)
    connection=sqlite3.connect(database);connection.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",("c","Event Alpha","event alpha","Currency A","red","2025-01-07","09:00",None,"fixture","c",None,None,None));connection.commit();connection.close()
    c=AppController(tmp_path);c.open_database(str(database));c.addRule();c.setSort("Oldest first");c.saveSearchAs("Oldest");c.newSearch();c.loadSearch("Oldest");assert c.resultSort=="oldest"
    spy=QSignalSpy(c.searchFinished);c.runSearch();assert wait_for_signal(spy);assert [item["date"] for item in c.resultModel.items]==["2025-01-06","2025-01-07"];c.shutdown()

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
    c.setSearchName("New search");spy=QSignalSpy(c.searchFinished);c.runSearch();assert wait_for_signal(spy)
    assert c.resultsCurrent and c.resultCount==1
    published=list(c.resultModel.items);release_old.set()
    # Release the old worker and wait through the controller's deterministic
    # QThread shutdown, then process its queued stale completion.
    c.shutdown();app.processEvents()
    assert list(c.resultModel.items)==published and spy.count()==1

def test_event_name_combo_accepts_typed_and_suggested_values(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr("ff_calendar_toolkit.mac_app.controller.QStandardPaths.writableLocation",lambda *_:str(tmp_path/"support"));database=tmp_path/"calendar.sqlite";make_database(database);c=AppController(tmp_path);c.open_database(str(database));c.addRule()
    engine=QQmlApplicationEngine();context=engine.rootContext()
    for name,value in {"controller":c,"ruleModel":c.ruleModel,"resultModel":c.resultModel,"eventModel":c.eventModel,"savedSearchModel":c.savedSearchModel}.items():context.setContextProperty(name,value)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1]/"ff_calendar_toolkit/mac_app/qml/Main.qml")));app.processEvents();combo=engine.rootObjects()[0].findChild(QObject,"eventNameCombo");assert combo is not None
    combo.setProperty("editText","Event Gamma");combo.accepted.emit();app.processEvents();assert c.definition.root.children[0].name=="Event Gamma"
    combo=engine.rootObjects()[0].findChild(QObject,"eventNameCombo");combo.setProperty("currentIndex",0);combo.activated.emit(0);app.processEvents();assert c.definition.root.children[0].name in c.eventNames;c.shutdown()
