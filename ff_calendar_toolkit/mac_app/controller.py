"""QObject bridge connecting every desktop action to application services."""
from __future__ import annotations
import copy,json,os,subprocess,time,uuid
from pathlib import Path
from threading import Event
from PySide6.QtCore import QAbstractListModel,QModelIndex,QObject,Property,Qt,QSettings,QStandardPaths,QThread,Signal,Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog,QMessageBox
from .database_reader import DatabaseReader,discover_database
from .diagnostics import collect
from .exports import export_csv,export_xlsx
from .filter_engine import search,validate
from .filter_schema import EventRule,RuleGroup,SearchDefinition,from_dict
from .saved_searches import SavedSearchStore

class DictListModel(QAbstractListModel):
    changed=Signal()
    def __init__(self,roles,parent=None):super().__init__(parent);self.roles=roles;self.items=[]
    def roleNames(self):return {Qt.UserRole+i+1:n.encode() for i,n in enumerate(self.roles)}
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.items)
    @Property(int,notify=changed)
    def count(self):return len(self.items)
    def data(self,index,role):
        if not index.isValid() or not 0<=index.row()<len(self.items):return None
        i=role-Qt.UserRole-1;return self.items[index.row()].get(self.roles[i]) if 0<=i<len(self.roles) else None
    def reset(self,items):self.beginResetModel();self.items=list(items);self.endResetModel();self.changed.emit()

class SearchWorker(QObject):
    """Run one immutable search request entirely in a dedicated Qt thread."""
    succeeded=Signal(int,object)
    failed=Signal(int,str)
    cancelled=Signal(int)
    finished=Signal()

    def __init__(self,generation,path,definition,cancel,search_function):
        super().__init__();self.generation=generation;self.path=path;self.definition=definition;self.cancel_event=cancel;self.search_function=search_function

    @Slot()
    def run(self):
        try:
            value=self.search_function(self.path,self.definition,self.cancel_event)
            if self.cancel_event.is_set():self.cancelled.emit(self.generation)
            else:self.succeeded.emit(self.generation,value)
        except Exception as exc:
            if self.cancel_event.is_set():self.cancelled.emit(self.generation)
            else:self.failed.emit(self.generation,str(exc))
        finally:self.finished.emit()

class AppController(QObject):
    stateChanged=Signal(); notification=Signal(str); error=Signal(str); searchFinished=Signal(); requestChooseDatabase=Signal()
    def __init__(self,repo_root=None,parent=None):
        super().__init__(parent);self.repo_root=Path(repo_root or Path.cwd());self.settings=QSettings();self.reader=None;self.facets={};self.definition=SearchDefinition();self.results=[];self.selected=None;self.loading=False;self.progress=0;self.last_export="";self._results_current=False;self._generation=0;self._cancel=Event();self._searches={}
        location=QStandardPaths.writableLocation(QStandardPaths.AppDataLocation);self.store=SavedSearchStore(location)
        self.ruleModel=DictListModel(["ruleId","label","mode","name","nameOperator","currencies","impacts","sources","timeMode","earliest","latest","rawTime","minimum","maximum","depth","groupOperator"])
        self.savedSearchModel=DictListModel(["name"]);self.resultModel=DictListModel(["date","matchedCount","totalCount"]);self.eventModel=DictListModel(["eventKey","sourceId","currency","impact","name","time","actual","forecast","previous","sourceType","matched","rules"])
        self._reload_saved();self.open_database(discover_database(self.settings.value("databasePath"),self.repo_root))
    @Property(bool,notify=stateChanged)
    def isLoading(self):return self.loading
    @Property(bool,notify=stateChanged)
    def resultsCurrent(self):return self._results_current
    @Property(str,notify=stateChanged)
    def searchName(self):return self.definition.name
    @Property(str,notify=stateChanged)
    def rootOperator(self):return self.definition.root.operator
    @Property(str,notify=stateChanged)
    def additionalPolicy(self):return self.definition.additional_policy
    @Property(str,notify=stateChanged)
    def resultSort(self):return self.definition.sort
    @Property(str,notify=stateChanged)
    def startDate(self):return self.definition.start_date or ""
    @Property(str,notify=stateChanged)
    def endDate(self):return self.definition.end_date or ""
    @Property('QVariantList',notify=stateChanged)
    def weekdays(self):return self.definition.weekdays
    @Property(str,notify=stateChanged)
    def globalCurrencies(self):return ", ".join(self.definition.currencies)
    @Property(str,notify=stateChanged)
    def globalImpacts(self):return ", ".join(self.definition.impacts)
    @Property(str,notify=stateChanged)
    def globalSources(self):return ", ".join(self.definition.source_types)
    @Property(int,notify=stateChanged)
    def minimumEvents(self):return self.definition.minimum_events
    @Property(int,notify=stateChanged)
    def maximumEvents(self):return -1 if self.definition.maximum_events is None else self.definition.maximum_events
    @Property(str,notify=stateChanged)
    def countedCurrencies(self):return ", ".join(self.definition.counted_currencies)
    @Property(str,notify=stateChanged)
    def countedImpacts(self):return ", ".join(self.definition.counted_impacts)
    @Property(str,notify=stateChanged)
    def applicationSupportPath(self):return str(self.store.directory)
    @Property(str,notify=stateChanged)
    def savedSearchPath(self):return str(self.store.path)
    @Property(str,notify=stateChanged)
    def logPath(self):return str(Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))/"logs"/"app.log")
    @Property(int,notify=stateChanged)
    def windowWidth(self):return max(1100,int(self.settings.value("windowWidth",1440)))
    @Property(int,notify=stateChanged)
    def windowHeight(self):return max(700,int(self.settings.value("windowHeight",900)))
    @Property(int,notify=stateChanged)
    def windowX(self):return max(0,int(self.settings.value("windowX",80)))
    @Property(int,notify=stateChanged)
    def windowY(self):return max(0,int(self.settings.value("windowY",80)))
    @Slot(int,int,int,int)
    def saveWindowGeometry(self,x,y,width,height):
        self.settings.setValue("windowX",max(0,x));self.settings.setValue("windowY",max(0,y));self.settings.setValue("windowWidth",width);self.settings.setValue("windowHeight",height)
    @Property(str,notify=stateChanged)
    def databasePath(self):return str(self.reader.path) if self.reader else ""
    @Property(str,notify=stateChanged)
    def databaseStatus(self):return "Connected — read only" if self.reader else "No compatible database selected"
    @Property(str,notify=stateChanged)
    def databaseSummary(self):
        if not self.reader:return "Choose a compatible SQLite database"
        m=self.reader.metadata();return f"{m['count']:,} events · {m['earliest'] or '—'} to {m['latest'] or '—'}\nModified {time.strftime('%Y-%m-%d %H:%M',time.localtime(m['modified']))}"
    @Property('QStringList',notify=stateChanged)
    def currencies(self):return self.facets.get("currencies",[])
    @Property('QStringList',notify=stateChanged)
    def impacts(self):return self.facets.get("impacts",[])
    @Property('QStringList',notify=stateChanged)
    def sources(self):return self.facets.get("sources",[])
    @Property('QStringList',notify=stateChanged)
    def eventNames(self):return self.facets.get("events",[])
    @Property(int,notify=stateChanged)
    def resultCount(self):return len(self.results)
    @Property(int,notify=stateChanged)
    def matchedEventCount(self):return sum(r.matched_event_count for r in self.results)
    @Property(int,notify=stateChanged)
    def totalEventCount(self):return sum(len(r.events) for r in self.results)
    @Slot(str,result=bool)
    def open_database(self,path):
        if not path:return False
        self.cancelSearch();self._invalidate_results()
        try:self.reader=DatabaseReader(path);self.facets=self.reader.facets();self.settings.setValue("databasePath",str(self.reader.path));self.stateChanged.emit();return True
        except Exception as exc:self.reader=None;self.facets={};self.error.emit(str(exc));self.stateChanged.emit();return False
    @Slot()
    def chooseDatabase(self):
        path,_=QFileDialog.getOpenFileName(None,"Choose Forex calendar database",self.databasePath or str(Path.home()),"SQLite databases (*.sqlite *.db);;All files (*)")
        if path:self.open_database(path)
    @Slot()
    def refreshDatabase(self):
        if self.reader:
            self.cancelSearch();self._invalidate_results()
            try:self.reader.validate();self.reader.metadata(True);self.facets=self.reader.facets();self.notification.emit("Database refreshed");self.stateChanged.emit()
            except Exception as exc:self.error.emit(str(exc))
    @Slot()
    def revealDatabase(self):self._reveal(self.databasePath)
    def _walk(self,node,depth=0):
        out=[]
        for c in node.children:
            if isinstance(c,RuleGroup):out.append({"ruleId":c.id,"label":"Nested group","depth":depth,"groupOperator":c.operator});out+=self._walk(c,depth+1)
            else:out.append({"ruleId":c.id,"label":c.label or c.id,"mode":c.mode,"name":c.name,"nameOperator":c.name_operator,"currencies":", ".join(c.currencies),"impacts":", ".join(c.impacts),"sources":", ".join(c.source_types),"timeMode":c.time_mode,"earliest":c.earliest_time or "","latest":c.latest_time or "","rawTime":c.raw_time,"minimum":c.minimum,"maximum":-1 if c.maximum is None else c.maximum,"depth":depth,"groupOperator":""})
        return out
    def _sync_rules(self):self.ruleModel.reset(self._walk(self.definition.root));self._invalidate_results();self.stateChanged.emit()
    def _invalidate_results(self):
        self._results_current=False;self.results=[];self.selected=None;self.resultModel.reset([]);self.eventModel.reset([])
    def _find(self,node,ident):
        for i,c in enumerate(node.children):
            if isinstance(c,RuleGroup) and c.id==ident:return node,i,c
            if isinstance(c,EventRule) and c.id==ident:return node,i,c
            if isinstance(c,RuleGroup):
                found=self._find(c,ident)
                if found:return found
        return None
    @Slot()
    def newSearch(self):self.cancelSearch();self.definition=SearchDefinition();self._sync_rules()
    @Slot(str)
    def setSearchName(self,name):self.definition.name=name.strip() or "Untitled Search";self._invalidate_results();self.stateChanged.emit()
    @Slot()
    def addRule(self):self.definition.root.children.append(EventRule(id=str(uuid.uuid4())));self._sync_rules()
    @Slot()
    def addGroup(self):self.definition.root.children.append(RuleGroup("AND",[EventRule(id=str(uuid.uuid4()))],str(uuid.uuid4())));self._sync_rules()
    def _group(self,ident):
        if ident in {"", "root"}:return self.definition.root
        found=self._find(self.definition.root,ident);return found[2] if found and isinstance(found[2],RuleGroup) else None
    @Slot(str)
    def addRuleToGroup(self,group_id):
        group=self._group(group_id)
        if group:group.children.append(EventRule(id=str(uuid.uuid4())));self._sync_rules()
    @Slot(str)
    def addGroupToGroup(self,group_id):
        group=self._group(group_id)
        if group:group.children.append(RuleGroup("AND",[],str(uuid.uuid4())));self._sync_rules()
    @Slot(str)
    def removeNode(self,ident):
        found=self._find(self.definition.root,ident)
        if found:found[0].children.pop(found[1]);self._sync_rules()
    @Slot(str)
    def duplicateRule(self,ident):
        found=self._find(self.definition.root,ident)
        if found and isinstance(found[2],EventRule):r=copy.deepcopy(found[2]);r.id=str(uuid.uuid4());found[0].children.insert(found[1]+1,r);self._sync_rules()
    @Slot(str,str)
    def updateGroup(self,ident,operator):
        found=self._find(self.definition.root,ident)
        if found and isinstance(found[2],RuleGroup) and operator in {"AND","OR"}:found[2].operator=operator;self._sync_rules()
    @Slot(str,str,'QVariant')
    def updateRule(self,ident,key,value):
        found=self._find(self.definition.root,ident)
        if not found:return
        mapping={"nameOperator":"name_operator","timeMode":"time_mode","rawTime":"raw_time","earliest":"earliest_time","latest":"latest_time","sources":"source_types"};attr=mapping.get(key,key)
        if attr in {"currencies","impacts","source_types"}:value=[x.strip() for x in str(value).split(",") if x.strip()]
        if attr in {"minimum","maximum"}:value=int(value) if str(value) not in {"","-1"} else None
        setattr(found[2],attr,value);self._sync_rules()
    @Slot(str)
    def setRootOperator(self,value):self.definition.root.operator=value;self._sync_rules()
    @Slot(str)
    def setSort(self,value):
        self.definition.sort="oldest" if "Oldest" in value else "newest"
        self._invalidate_results();self.stateChanged.emit()
    @Slot(str)
    def setPolicy(self,label):self.definition.additional_policy={"Allow additional events":"allow","Only within counted scope":"counted_scope","Exact event set":"exact"}.get(label,label);self._invalidate_results();self.stateChanged.emit()
    @Slot(str,str)
    def setGlobal(self,key,value):
        lists={"currencies","impacts","source_types","counted_currencies","counted_impacts"}
        try:
            if key in lists:setattr(self.definition,key,[x.strip() for x in value.split(",") if x.strip()])
            elif key in {"start_date","end_date"}:setattr(self.definition,key,value.strip() or None)
            elif key in {"minimum_events","maximum_events"}:setattr(self.definition,key,int(value) if value.strip() else (0 if key=="minimum_events" else None))
        except ValueError:self.error.emit(f"{key.replace('_',' ').title()} must be a whole number");return
        self._invalidate_results()
        self.stateChanged.emit()
    @Slot('QVariantList')
    def setWeekdays(self,value):self.definition.weekdays=sorted({int(x) for x in value});self._invalidate_results();self.stateChanged.emit()
    @Slot(int,bool)
    def toggleWeekday(self,weekday,enabled):
        values=set(self.definition.weekdays)
        values.add(weekday) if enabled else values.discard(weekday)
        self.definition.weekdays=sorted(values);self._invalidate_results();self.stateChanged.emit()
    @Slot(result=str)
    def validationMessage(self):return "\n".join(validate(self.definition))
    @Slot()
    def runSearch(self):
        if not self.reader:self.error.emit("Choose a database before searching");return
        errors=validate(self.definition)
        if errors:self.error.emit("\n".join(errors));return
        self._generation+=1;generation=self._generation;self._cancel.set();self._cancel=Event();cancel=self._cancel;definition=copy.deepcopy(self.definition);path=self.reader.path;self.loading=True;self.stateChanged.emit()
        thread=QThread();worker=SearchWorker(generation,path,definition,cancel,self._search_worker);worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._publish,Qt.QueuedConnection);worker.failed.connect(self._search_failed,Qt.QueuedConnection);worker.cancelled.connect(self._search_cancelled,Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater);worker.finished.connect(thread.quit,Qt.DirectConnection)
        thread.finished.connect(self._thread_finished,Qt.QueuedConnection)
        self._searches[thread]=(worker,cancel);thread.start()
    @staticmethod
    def _search_worker(path,definition,cancel):
        # Policies inspect the complete event set on each candidate date. Global
        # restrictions are intentionally applied only by the filter engine.
        reader=DatabaseReader(path);events=reader.events(definition.start_date,definition.end_date);return search(events,definition,cancel)
    @Slot(int,object)
    def _publish(self,generation,value):
        if generation!=self._generation:return
        self.loading=False
        self.results=value;self._results_current=True;self.resultModel.reset([{"date":r.date_et,"matchedCount":r.matched_event_count,"totalCount":len(r.events)} for r in value]);self.selectDate(value[0].date_et if value else "");self.searchFinished.emit()
        self.stateChanged.emit()
    @Slot(int,str)
    def _search_failed(self,generation,message):
        if generation!=self._generation:return
        self.loading=False;self.error.emit(message);self.stateChanged.emit()
    @Slot(int)
    def _search_cancelled(self,generation):
        if generation!=self._generation:return
        self.loading=False;self.stateChanged.emit()
    @Slot()
    def _thread_finished(self):
        thread=self.sender()
        if thread in self._searches:
            self._searches.pop(thread)
            thread.deleteLater()
    @Slot()
    def cancelSearch(self):self._generation+=1;self._cancel.set();self.loading=False;self.stateChanged.emit()
    @Slot(str)
    def selectDate(self,day):
        result=next((r for r in self.results if r.date_et==day),None);self.selected=day
        if not result:self.eventModel.reset([]);return
        matched={k for values in result.matches.values() for k in values};self.eventModel.reset([{"eventKey":e.event_key,"sourceId":e.source_event_id or "","currency":e.currency,"impact":e.impact_color,"name":e.event_name,"time":e.time_et or e.raw_time or "Clockless","actual":e.actual or "","forecast":e.forecast or "","previous":e.previous or "","sourceType":e.source_type,"matched":e.event_key in matched,"rules":", ".join(k for k,v in result.matches.items() if e.event_key in v)} for e in result.events])
    def _reload_saved(self):
        searches=self.store.load();self.savedSearchModel.reset([{"name":n} for n in sorted(searches)]);
        if self.store.warning:self.notification.emit(self.store.warning)
    @Slot()
    def saveSearch(self):self.store.save(self.definition);self._reload_saved();self.notification.emit("Search saved")
    def _validated_name(self,name):
        value=name.strip()
        if not value:self.error.emit("Search name cannot be blank");return None
        return value
    def _may_replace(self,name,ignore=None):
        if name==ignore or name not in self.store.load():return True
        return QMessageBox.question(None,"Replace Saved Search",f'A saved search named "{name}" already exists. Replace it?')==QMessageBox.Yes
    @Slot(str,result=bool)
    def saveSearchAs(self,name):
        value=self._validated_name(name)
        if not value or not self._may_replace(value):return False
        self.definition.name=value;self.store.save(self.definition);self._reload_saved();self._invalidate_results();self.stateChanged.emit();self.notification.emit("Search saved");return True
    @Slot(str)
    def loadSearch(self,name):
        item=self.store.load().get(name)
        if item:self.cancelSearch();self.definition=item;self._sync_rules()
    @Slot(str,str,result=bool)
    def renameSearch(self,old,new):
        value=self._validated_name(new);searches=self.store.load();item=searches.get(old)
        if not item or not value or not self._may_replace(value,old):return False
        searches.pop(old);item.name=value;searches[value]=item;self.store.write(searches);self._reload_saved();return True
    @Slot(str,str,result=bool)
    def duplicateSearch(self,name,new):
        value=self._validated_name(new);item=self.store.load().get(name)
        if not item or not value or not self._may_replace(value):return False
        item=copy.deepcopy(item);item.name=value;self.store.save(item);self._reload_saved();return True
    @Slot(str)
    def deleteSearch(self,name):
        answer=QMessageBox.question(None,"Delete Saved Search",f'Delete "{name}"?')
        if answer==QMessageBox.Yes:self.store.delete(name);self._reload_saved()
    @Slot(str)
    def deleteSearchConfirmed(self,name):self.store.delete(name);self._reload_saved()
    @Slot()
    def importSearch(self):
        path,_=QFileDialog.getOpenFileName(None,"Import search",str(Path.home()),"JSON (*.json)")
        if path:
            try:self.definition=from_dict(json.loads(Path(path).read_text()));self._sync_rules();self.notification.emit("Search imported")
            except Exception as exc:self.error.emit(str(exc))
    @Slot()
    def exportSearch(self):
        path,_=QFileDialog.getSaveFileName(None,"Export search",f"{self.definition.name}.json","JSON (*.json)")
        if path:Path(path).write_text(json.dumps(self.definition.to_dict(),indent=2));self.last_export=path;self.notification.emit("Search definition exported")
    @Slot(str,str)
    def exportResults(self,format,scope):
        suffix="xlsx" if format=="xlsx" else "csv";path,_=QFileDialog.getSaveFileName(None,"Export results",f"{self.definition.name}.{suffix}",f"{suffix.upper()} (*.{suffix})")
        if not path:return
        try:
            if suffix=="csv":export_csv(path,self.results,scope)
            else:export_xlsx(path,self.results,self.definition,self.reader.metadata() if self.reader else {},scope)
            self.last_export=path;self.notification.emit(f"Exported {path}")
        except Exception as exc:self.error.emit(str(exc))
    @Slot(str,str,result=bool)
    def exportCsvTo(self,path,scope="all_events"):
        try:export_csv(path,self.results,scope);self.last_export=path;return True
        except Exception as exc:self.error.emit(str(exc));return False
    @Slot(str,str,result=bool)
    def exportXlsxTo(self,path,scope="all_events"):
        try:export_xlsx(path,self.results,self.definition,self.reader.metadata() if self.reader else {},scope);self.last_export=path;return True
        except Exception as exc:self.error.emit(str(exc));return False
    @Slot()
    def copyMatchingDates(self):QGuiApplication.clipboard().setText("\n".join(r.date_et for r in self.results));self.notification.emit("Matching dates copied")
    @Slot()
    def copySearchDefinition(self):QGuiApplication.clipboard().setText(json.dumps(self.definition.to_dict(),indent=2));self.notification.emit("Search definition copied")
    @Slot()
    def revealExport(self):self._reveal(self.last_export)
    @Slot()
    def copyDiagnostics(self):QGuiApplication.clipboard().setText(json.dumps(collect(self.reader.metadata() if self.reader else {}),indent=2));self.notification.emit("Diagnostics copied")
    @Slot(result=str)
    def diagnostics(self):return json.dumps(collect(self.reader.metadata() if self.reader else {}),indent=2)
    def _reveal(self,path):
        if not path:return
        if sys.platform=="darwin":subprocess.Popen(["open","-R",path])
        else:subprocess.Popen(["xdg-open",str(Path(path).parent)])
    def shutdown(self):
        self.cancelSearch()
        # Retain every worker/thread pair until its thread has actually stopped.
        # wait() is safe here: workers observe threading.Event and never need the
        # application event loop in order to complete.
        for thread,(worker,cancel) in list(self._searches.items()):
            cancel.set();thread.wait()
        self._searches.clear()

import sys
