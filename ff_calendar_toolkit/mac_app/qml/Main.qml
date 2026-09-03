import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "components"

ApplicationWindow {
    id:root
    objectName:"mainWindow"
    visible:true
    width:controller.windowWidth;height:controller.windowHeight;x:controller.windowX;y:controller.windowY
    minimumWidth:1100;minimumHeight:700
    title:controller.searchName+" — Forex Calendar Lab"
    color:DesignTokens.window
    palette { window:DesignTokens.window;windowText:DesignTokens.text;base:DesignTokens.surface;text:DesignTokens.text;button:DesignTokens.surface;buttonText:DesignTokens.text;highlight:DesignTokens.accent }
    property string selectedRule:""
    property string renameSource:""
    property bool sidebarShown:controller.sidebarVisible
    onClosing:function(close){controller.saveWindowGeometry(x,y,width,height);controller.savePaneWidths(workspace.width,results.width)}

    Connections { target:controller
        function onError(message){errorDialog.text=message;errorDialog.open()}
        function onNotification(message){announcement.text=message;announcement.visible=true;announcementTimer.restart()}
    }
    Timer{id:announcementTimer;interval:4000;onTriggered:announcement.visible=false}
    Label {
        id: announcement
        visible: false
        z: 100
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: DesignTokens.section
        padding: DesignTokens.spaceLarge
        text: ""
        color: DesignTokens.success
        background: Rectangle {
            color: DesignTokens.surface
            radius: DesignTokens.radius
            border.color: DesignTokens.success
        }
        Accessible.name: text
    }
    MessageDialog{id:errorDialog;title:"Forex Calendar Lab"}
    Dialog{id:about;title:"About Forex Calendar Lab";standardButtons:Dialog.Ok;width:520;contentItem:TextArea{text:"Forex Calendar Lab\n\nOffline, read-only historical calendar analysis.\n\n"+controller.diagnostics();readOnly:true;wrapMode:TextEdit.Wrap}}
    Dialog{id:settingsDialog;title:"Settings";modal:true;width:620;standardButtons:Dialog.Close;ColumnLayout{Label{text:"Database path";font.bold:true}Label{text:controller.databasePath||"None selected";wrapMode:Text.WrapAnywhere;Layout.fillWidth:true}Button{text:"Choose Database…";onClicked:controller.chooseDatabase()}Label{text:"Application support";font.bold:true}Label{text:controller.applicationSupportPath;wrapMode:Text.WrapAnywhere;Layout.fillWidth:true}Label{text:"Application log";font.bold:true}Label{text:controller.logPath;wrapMode:Text.WrapAnywhere;Layout.fillWidth:true}}}
    Dialog{id:saveAsDialog;title:"Save Search As";modal:true;standardButtons:Dialog.Save|Dialog.Cancel;onAccepted:controller.saveSearchAs(saveAsName.text);TextField{id:saveAsName;width:340;placeholderText:"Search name";Accessible.name:"New search name"}}
    Dialog{id:renameDialog;title:"Rename Saved Search";modal:true;standardButtons:Dialog.Save|Dialog.Cancel;onAccepted:controller.renameSearch(root.renameSource,renameName.text);TextField{id:renameName;width:340;Accessible.name:"New saved-search name"}}
    Dialog{id:exportDialog;title:"Export Results";modal:true;standardButtons:Dialog.Close;ColumnLayout{Label{text:"Export scope"}ComboBox{id:exportScope;model:["all_events","matched_events","matching_dates"];Accessible.name:"Export scope"}RowLayout{Button{text:"Export CSV…";onClicked:controller.exportResults("csv",exportScope.currentText)}Button{text:"Export XLSX…";onClicked:controller.exportResults("xlsx",exportScope.currentText)}}Button{text:"Copy Matching Dates";onClicked:controller.copyMatchingDates()}Button{text:"Reveal Last Export";enabled:controller.hasLastExport;onClicked:controller.revealExport()}}}

    Shortcut{sequences:["Ctrl+Return","Meta+Return"];onActivated:controller.runSearch()}
    Shortcut{sequences:[StandardKey.Cancel];enabled:controller.isLoading;onActivated:controller.cancelSearch()}
    Action{id:newAction;text:"New Search";shortcut:StandardKey.New;onTriggered:controller.newSearch()}
    Action{id:saveAction;text:"Save";shortcut:StandardKey.Save;onTriggered:controller.saveSearch()}
    Action{id:saveAsAction;text:"Save As…";shortcut:StandardKey.SaveAs;onTriggered:saveAsDialog.open()}
    Action{id:importAction;text:"Import Search Definition…";shortcut:StandardKey.Open;onTriggered:controller.importSearch()}
    Action{id:copyAction;text:"Copy Search Definition";shortcut:"Ctrl+Shift+C";onTriggered:controller.copySearchDefinition()}
    Action{id:deleteAction;text:"Delete Selected Rule or Group";enabled:root.selectedRule!=="";onTriggered:controller.removeNode(root.selectedRule)}
    Action{id:helpAction;text:"Forex Calendar Lab Help";shortcut:StandardKey.HelpContents;onTriggered:about.open()}
    Action{id:settingsAction;text:"Settings…";shortcut:StandardKey.Preferences;onTriggered:settingsDialog.open()}
    Action{id:quitAction;text:"Quit Forex Calendar Lab";shortcut:StandardKey.Quit;onTriggered:Qt.quit()}
    menuBar:MenuBar{
        Menu{title:"Forex Calendar Lab";MenuItem{text:"About Forex Calendar Lab";onTriggered:about.open()}MenuItem{action:settingsAction}MenuSeparator{}MenuItem{text:"Minimize";onTriggered:root.showMinimized()}MenuSeparator{}MenuItem{action:quitAction}}
        Menu{title:"File";MenuItem{action:newAction}MenuSeparator{}MenuItem{action:saveAction}MenuItem{action:saveAsAction}MenuSeparator{}MenuItem{action:importAction}MenuItem{text:"Export Search Definition…";onTriggered:controller.exportSearch()}MenuItem{text:"Export Results…";enabled:controller.resultsCurrent;onTriggered:exportDialog.open()}MenuSeparator{}MenuItem{text:"Choose Database…";onTriggered:controller.chooseDatabase()}}
        Menu{title:"Edit";MenuItem{text:"Duplicate Selected Rule or Group";enabled:root.selectedRule!=="";onTriggered:controller.duplicateNode(root.selectedRule)}MenuItem{action:deleteAction}MenuSeparator{}MenuItem{action:copyAction}}
        Menu{title:"View";MenuItem{text:root.sidebarShown?"Hide Sidebar":"Show Sidebar";onTriggered:{root.sidebarShown=!root.sidebarShown;controller.saveSidebarState(root.sidebarShown,sidebar.userWidth)}}MenuItem{text:"List View";onTriggered:controller.saveResultsView(0)}MenuItem{text:"Grid View";onTriggered:controller.saveResultsView(1)}MenuSeparator{}MenuItem{text:"Reset Pane Layout";onTriggered:{sidebar.userWidth=250;workspace.SplitView.preferredWidth=680;results.SplitView.preferredWidth=470;controller.saveSidebarState(root.sidebarShown,250);controller.savePaneWidths(680,470)}}}
        Menu{title:"Help";MenuItem{action:helpAction}MenuItem{text:"Copy Diagnostics";onTriggered:controller.copyDiagnostics()}MenuItem{text:"Reveal Log";onTriggered:controller.revealLog()}}
    }
    header:AppToolbar{onSaveAsRequested:saveAsDialog.open();onExportRequested:exportDialog.open()}

    SplitView{id:split;anchors.fill:parent;orientation:Qt.Horizontal
        NavigationSidebar{id:sidebar;visible:root.sidebarShown;SplitView.preferredWidth:userWidth;SplitView.minimumWidth:190;SplitView.maximumWidth:420;onRenameRequested:function(oldName){root.renameSource=oldName;renameName.text=oldName;renameDialog.open()}}
        ScrollView{id:workspace;objectName:"ruleWorkspace";SplitView.fillWidth:true;SplitView.preferredWidth:controller.workspaceWidth;SplitView.minimumWidth:520
            Item{width:parent.width;implicitHeight:workspaceColumn.implicitHeight+DesignTokens.section*2
                ColumnLayout{id:workspaceColumn;x:DesignTokens.section;y:DesignTokens.section;width:parent.width-DesignTokens.section*2;spacing:DesignTokens.section
                    GlobalFilters{Layout.fillWidth:true}
                    RuleBuilder{Layout.fillWidth:true;onSelected:identifier=>root.selectedRule=identifier}
                    AdditionalPolicy{Layout.fillWidth:true}
                    StatusBanner{Layout.fillWidth:true;kind:"error";message:controller.validationMessage()}
                }
            }
        }
        ResultsPane{id:results;objectName:"resultsPane";SplitView.preferredWidth:controller.resultsPaneWidth;SplitView.minimumWidth:350}
    }
}
