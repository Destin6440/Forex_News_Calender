import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "components"
ApplicationWindow {
 id: root; visible:true; width:controller.windowWidth; height:controller.windowHeight; x:controller.windowX; y:controller.windowY; minimumWidth:1100; minimumHeight:700; title:"Forex Calendar Lab"; color:"#09111f"
 onClosing:function(close){controller.saveWindowGeometry(x,y,width,height)}
 palette { window:"#09111f"; windowText:"#e7edf5"; base:"#111b2b"; text:"#e7edf5"; button:"#172438"; buttonText:"#e7edf5"; highlight:"#22d3ee" }
 property string selectedRule:""; property string toast:""
 Connections { target:controller; function onNotification(message){toast=message} function onError(message){errorDialog.text=message;errorDialog.open()} function onStateChanged(){searchName.text=controller.searchName;startField.text=controller.startDate;endField.text=controller.endDate;minimumField.text=String(controller.minimumEvents);maximumField.text=controller.maximumEvents<0?"":String(controller.maximumEvents)} }
 MessageDialog { id:errorDialog; title:"Forex Calendar Lab" }
 Dialog { id:about; title:"About Forex Calendar Lab"; standardButtons:Dialog.Ok; width:520; contentItem:TextArea { text:"Forex Calendar Lab 1.0.0\n\nOffline generic historical calendar analysis.\n\n"+controller.diagnostics(); readOnly:true; wrapMode:TextEdit.Wrap } }
 Dialog{id:settingsDialog;title:"Settings";modal:true;width:600;standardButtons:Dialog.Close;ColumnLayout{Label{text:"Current database";font.bold:true}Label{text:controller.databasePath||"None selected";wrapMode:Text.WrapAnywhere;Layout.fillWidth:true}Button{text:"Choose Database";onClicked:controller.chooseDatabase()}Label{text:"Application support";font.bold:true}Label{text:controller.applicationSupportPath;wrapMode:Text.WrapAnywhere;Layout.fillWidth:true}Label{text:"Saved searches";font.bold:true}Label{text:controller.savedSearchPath;wrapMode:Text.WrapAnywhere;Layout.fillWidth:true}Label{text:"Application log";font.bold:true}Label{text:controller.logPath;wrapMode:Text.WrapAnywhere;Layout.fillWidth:true}}}
 Dialog { id:saved; title:"Saved Searches"; modal:true; width:520; height:500; standardButtons:Dialog.Close
  ColumnLayout { anchors.fill:parent; ListView { Layout.fillWidth:true; Layout.fillHeight:true; model:savedSearchModel; delegate:RowLayout { width:ListView.view.width; property string savedName:name; TextField{id:renameField;text:savedName;Layout.fillWidth:true} Button{text:"Load";onClicked:{controller.loadSearch(savedName);saved.close()}} Button{text:"Rename";onClicked:controller.renameSearch(savedName,renameField.text)} Button{text:"Duplicate";onClicked:controller.duplicateSearch(savedName,savedName+" Copy")} Button{text:"Delete";onClicked:controller.deleteSearch(savedName)} } } RowLayout { Button{text:"Import JSON";onClicked:controller.importSearch()} Button{text:"Export current JSON";onClicked:controller.exportSearch()} } }
 }
 Dialog{id:saveAs;title:"Save Search As";modal:true;standardButtons:Dialog.Save|Dialog.Cancel;onAccepted:controller.saveSearchAs(saveAsName.text);TextField{id:saveAsName;placeholderText:"Search name";width:320}}
 Dialog { id:exports; title:"Export results"; modal:true; standardButtons:Dialog.Close
  ColumnLayout { ComboBox{id:scope;model:["all_events","matched_events","matching_dates"]} RowLayout{Button{text:"Export CSV";onClicked:controller.exportResults("csv",scope.currentText)} Button{text:"Export XLSX";onClicked:controller.exportResults("xlsx",scope.currentText)}} Button{text:"Copy Matching Dates";onClicked:controller.copyMatchingDates()} Button{text:"Copy Search Definition";onClicked:controller.copySearchDefinition()} Button{text:"Reveal Last Export";onClicked:controller.revealExport()} }
 }
 Shortcut { sequence:StandardKey.New; onActivated:controller.newSearch() } Shortcut { sequence:StandardKey.Save;onActivated:controller.saveSearch()} Shortcut { sequence:StandardKey.Refresh;onActivated:controller.refreshDatabase()} Shortcut { sequence:"Ctrl+E";onActivated:exports.open()} Shortcut { sequence:StandardKey.Cancel;onActivated:controller.cancelSearch()} Shortcut { sequence:"Ctrl+Return";onActivated:controller.runSearch()}
 component Card: Rectangle { color:"#111b2b";radius:10;border.color:"#26364d" }
 RowLayout { anchors.fill:parent; spacing:0
  Rectangle { Layout.preferredWidth:260;Layout.fillHeight:true;color:"#0c1626";border.color:"#26364d"
   ColumnLayout { anchors.fill:parent;anchors.margins:14
    Label{text:"FOREX CALENDAR LAB";color:"#22d3ee";font.bold:true} Button{text:"＋ New Search";Layout.fillWidth:true;onClicked:controller.newSearch()} Button{text:"☆ Saved Searches";Layout.fillWidth:true;onClicked:saved.open()}
    Label{text:"DATABASE";color:"#8090a6"} Label{text:controller.databaseStatus;font.bold:true;wrapMode:Text.Wrap;Layout.fillWidth:true} Label{text:controller.databasePath;color:"#93a4b8";wrapMode:Text.WrapAnywhere;Layout.fillWidth:true} Label{text:controller.databaseSummary;color:"#93a4b8";wrapMode:Text.Wrap;Layout.fillWidth:true}
    Button{text:"Choose Database";Layout.fillWidth:true;onClicked:controller.chooseDatabase()} Button{text:"Refresh Database";Layout.fillWidth:true;onClicked:controller.refreshDatabase()} Button{text:"Reveal in Finder";enabled:controller.databasePath!=="";Layout.fillWidth:true;onClicked:controller.revealDatabase()}
    Label{text:"AVAILABLE VALUES";color:"#8090a6"} Label{text:controller.currencies.length+" currencies · "+controller.impacts.length+" impacts\n"+controller.sources.length+" source types · "+controller.eventNames.length+" event names";wrapMode:Text.Wrap}
    Item{Layout.fillHeight:true} Button{text:"Settings";Layout.fillWidth:true;onClicked:settingsDialog.open()} Button{text:"Copy Diagnostics";Layout.fillWidth:true;onClicked:controller.copyDiagnostics()} Button{text:"Help / About";Layout.fillWidth:true;onClicked:about.open()}
   }
  }
  ColumnLayout { Layout.fillWidth:true;Layout.fillHeight:true;spacing:0
   Rectangle { Layout.fillWidth:true;height:64;color:"#0e1929"; RowLayout { anchors.fill:parent;anchors.margins:12
    TextField{id:searchName;objectName:"searchNameField";text:controller.searchName;placeholderText:"Search name";Layout.preferredWidth:300;onEditingFinished:controller.setSearchName(text)} Item{Layout.fillWidth:true} Button{text:"Save";onClicked:controller.saveSearch()} Button{text:"Save As";onClicked:saveAs.open()} Button{text:"Export";enabled:controller.resultCount>0&&controller.resultsCurrent;onClicked:exports.open()} Button{text:controller.isLoading?"Cancel":"Run Search";highlighted:true;onClicked:controller.isLoading?controller.cancelSearch():controller.runSearch()}
   }}
   SplitView { Layout.fillWidth:true;Layout.fillHeight:true
    ScrollView { SplitView.fillWidth:true;SplitView.minimumWidth:650
     ColumnLayout { width:parent.width;leftPadding:18;rightPadding:18;topPadding:18;spacing:12
      RowLayout { Label{text:"Rule Builder";font.pixelSize:22;font.bold:true} Item{Layout.fillWidth:true} ComboBox{model:["AND","OR"];currentIndex:model.indexOf(controller.rootOperator);onActivated:controller.setRootOperator(currentText)} }
      Label{text:"Currency, impact, source, and event suggestions come from the selected database.";color:"#93a4b8"}
      ListView { Layout.fillWidth:true;implicitHeight:Math.max(150,contentHeight);model:ruleModel;interactive:false;spacing:10
       delegate:Card { x:Math.min(depth*18,120);width:ListView.view.width-x;height:groupOperator!==""?60:260
        Loader { anchors.fill:parent;anchors.margins:10;sourceComponent:groupOperator!==""?groupCard:ruleCard }
        Component{id:groupCard;RowLayout{Label{text:"Nested group";font.bold:true}ComboBox{model:["AND","OR"];currentIndex:model.indexOf(groupOperator);onActivated:controller.updateGroup(ruleId,currentText)}Button{text:"Add Rule";onClicked:controller.addRuleToGroup(ruleId)}Button{text:"Add Group";onClicked:controller.addGroupToGroup(ruleId)}Item{Layout.fillWidth:true}Button{text:"Delete Group";onClicked:controller.removeNode(ruleId)}}}
        Component{id:ruleCard;ColumnLayout{
         RowLayout{Layout.fillWidth:true;Label{text:"Rule";font.bold:true}ComboBox{id:modeBox;model:["required","optional","excluded"];currentIndex:model.indexOf(mode);onActivated:controller.updateRule(ruleId,"mode",currentText)}Item{Layout.fillWidth:true}Button{text:"Duplicate";onClicked:controller.duplicateRule(ruleId)}Button{text:"Delete";onClicked:controller.removeNode(ruleId)}}
         RowLayout{Layout.fillWidth:true;TextField{placeholderText:"Rule label (optional)";text:label;onEditingFinished:controller.updateRule(ruleId,"label",text)}ComboBox{id:eventName;objectName:"eventNameCombo";editable:true;model:controller.eventNames;editText:name;Layout.fillWidth:true;onAccepted:controller.updateRule(ruleId,"name",editText);onActivated:function(index){controller.updateRule(ruleId,"name",model[index])};onActiveFocusChanged:if(!activeFocus&&editText!==name)controller.updateRule(ruleId,"name",editText)}ComboBox{id:op;model:["contains","exact","starts_with","ends_with","regex"];currentIndex:model.indexOf(nameOperator);onActivated:controller.updateRule(ruleId,"nameOperator",currentText)}}
         RowLayout{Layout.fillWidth:true;MultiSelect{Layout.fillWidth:true;options:controller.currencies;selectedText:currencies;onSelectionChanged:value=>controller.updateRule(ruleId,"currencies",value)}MultiSelect{Layout.fillWidth:true;options:controller.impacts;selectedText:impacts;onSelectionChanged:value=>controller.updateRule(ruleId,"impacts",value)}MultiSelect{Layout.fillWidth:true;options:controller.sources;selectedText:sources;onSelectionChanged:value=>controller.updateRule(ruleId,"sources",value)}}
         RowLayout{ComboBox{id:tm;model:["any","timed","clockless"];currentIndex:model.indexOf(timeMode);onActivated:controller.updateRule(ruleId,"timeMode",currentText)}TextField{placeholderText:"Earliest HH:MM";text:earliest;onEditingFinished:controller.updateRule(ruleId,"earliest",text)}TextField{placeholderText:"Latest HH:MM";text:latest;onEditingFinished:controller.updateRule(ruleId,"latest",text)}TextField{placeholderText:"Raw clockless label";text:rawTime;onEditingFinished:controller.updateRule(ruleId,"rawTime",text)}}
         RowLayout{Label{text:"Occurrences"}SpinBox{from:0;to:99;value:minimum;onValueModified:controller.updateRule(ruleId,"minimum",value)}Label{text:"to"}SpinBox{from:-1;to:99;value:maximum;editable:true;onValueModified:controller.updateRule(ruleId,"maximum",value)}Label{text:"(-1 = unlimited)";color:"#93a4b8"}}
        }}
       }
      }
      Card { visible:ruleModel.count===0;Layout.fillWidth:true;height:150;Column{anchors.centerIn:parent;spacing:8;Label{text:"Start with an empty filter";font.pixelSize:18;font.bold:true}Label{text:"Add any rule or nested group—no presets are installed.";color:"#93a4b8"}} }
      RowLayout{Button{text:"＋ Add Rule";onClicked:controller.addRule()}Button{text:"⊕ Add Nested Group";onClicked:controller.addGroup()}Button{text:"Clear Search";onClicked:controller.newSearch()}}
      Label{text:"Additional-event policy";font.bold:true}ComboBox{Layout.fillWidth:true;model:["Allow additional events","Only within counted scope","Exact event set"];currentIndex:["allow","counted_scope","exact"].indexOf(controller.additionalPolicy);onActivated:controller.setPolicy(currentText)}
      GridLayout{columns:2;Layout.fillWidth:true
       TextField{id:startField;placeholderText:"Start date YYYY-MM-DD";text:controller.startDate;Layout.fillWidth:true;onEditingFinished:controller.setGlobal("start_date",text)} TextField{id:endField;placeholderText:"End date YYYY-MM-DD";text:controller.endDate;Layout.fillWidth:true;onEditingFinished:controller.setGlobal("end_date",text)}
       MultiSelect{options:controller.currencies;selectedText:controller.globalCurrencies;onSelectionChanged:value=>controller.setGlobal("currencies",value)} MultiSelect{options:controller.impacts;selectedText:controller.globalImpacts;onSelectionChanged:value=>controller.setGlobal("impacts",value)}
       MultiSelect{options:controller.sources;selectedText:controller.globalSources;onSelectionChanged:value=>controller.setGlobal("source_types",value)} MultiSelect{options:controller.currencies;selectedText:controller.countedCurrencies;onSelectionChanged:value=>controller.setGlobal("counted_currencies",value)}
       MultiSelect{options:controller.impacts;selectedText:controller.countedImpacts;onSelectionChanged:value=>controller.setGlobal("counted_impacts",value)}
       TextField {
        id: minimumField
        placeholderText: "Minimum total events (0)"
        text: String(controller.minimumEvents)
        Layout.fillWidth: true
        validator: IntValidator { bottom: 0 }
        onEditingFinished: controller.setGlobal("minimum_events", text)
       }
       TextField {
        id: maximumField
        placeholderText: "Maximum total events (none)"
        text: controller.maximumEvents < 0 ? "" : String(controller.maximumEvents)
        Layout.fillWidth: true
        validator: IntValidator { bottom: 0 }
        onEditingFinished: controller.setGlobal("maximum_events", text)
       }
      }
      RowLayout{Label{text:"Weekdays";font.bold:true}Repeater{model:["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];CheckBox{required property int index;required property string modelData;text:modelData;checked:controller.weekdays.indexOf(index)>=0;onToggled:controller.toggleWeekday(index,checked)}}}
      Label{text:controller.validationMessage();visible:text!=="";color:"#fb7185";wrapMode:Text.Wrap;Layout.fillWidth:true}Item{height:16}
     }
    }
    Card { SplitView.preferredWidth:470;SplitView.minimumWidth:380;radius:0
     ColumnLayout { anchors.fill:parent;anchors.margins:14
      RowLayout{Label{text:"Results";font.pixelSize:22;font.bold:true}Item{Layout.fillWidth:true}ComboBox{id:sortCombo;objectName:"resultSortCombo";model:["Newest first","Oldest first"];currentIndex:controller.resultSort==="oldest"?1:0;onActivated:controller.setSort(currentText)}BusyIndicator{running:controller.isLoading;visible:running}}
      Label{text:controller.resultCount+" dates · "+controller.matchedEventCount+" matched · "+controller.totalEventCount+" total";color:"#93a4b8"}
      TabBar{id:views;Layout.fillWidth:true;TabButton{text:"List"}TabButton{text:"Calendar"}}
      ListView { visible:views.currentIndex===0;Layout.fillWidth:true;Layout.preferredHeight:220;model:resultModel;spacing:6;delegate:Button{width:ListView.view.width;text:date+"   "+matchedCount+" matched · "+totalCount+" total";onClicked:controller.selectDate(date)} }
      GridView { visible:views.currentIndex===1;Layout.fillWidth:true;Layout.preferredHeight:220;cellWidth:108;cellHeight:70;model:resultModel;delegate:Button{width:100;height:62;text:date.slice(5)+"\n"+matchedCount+" matched";onClicked:controller.selectDate(date)} }
      Label{text:"Selected date events";font.bold:true}ListView { Layout.fillWidth:true;Layout.fillHeight:true;model:eventModel;spacing:6;delegate:Card{width:ListView.view.width;height:118;border.color:matched?"#22d3ee":"#26364d";Column{anchors.fill:parent;anchors.margins:9;spacing:3;Label{text:(matched?"MATCHED":"UNMATCHED")+" · "+currency+" · "+impact+" · "+time;color:matched?"#34d399":"#93a4b8";font.bold:true}Label{text:name;font.bold:true}Label{text:"Actual "+actual+"   Forecast "+forecast+"   Previous "+previous;color:"#b8c5d6"}Label{text:"Rules: "+(rules||"—")+" · Source: "+sourceType+" · ID: "+sourceId;color:"#8090a6"}Label{text:"Event key: "+eventKey;color:"#65758a"}}} }
      Label{visible:!controller.isLoading&&controller.resultCount===0;text:ruleModel.count===0?"Add a rule to begin.":"No matching dates. Adjust the filter and try again.";color:"#93a4b8"}
      Label{text:toast;color:"#34d399";visible:text!==""}
     }
    }
   }
  }
 }
}
