import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    id:pane;color:DesignTokens.window
    ColumnLayout { anchors.fill:parent;anchors.margins:DesignTokens.section;spacing:DesignTokens.spaceLarge
        RowLayout{Layout.fillWidth:true;Label{text:"Results";font.pixelSize:18;font.bold:true}Item{Layout.fillWidth:true}Label{text:controller.resultCount+" dates · "+controller.matchedEventCount+" matched · "+controller.totalEventCount+" total";color:DesignTokens.secondaryText;Accessible.name:text}}
        StatusBanner{Layout.fillWidth:true;visible:controller.resultsStale;kind:"warning";message:"Search definition changed — run the search again to refresh results."}
        StatusBanner{Layout.fillWidth:true;visible:controller.searchState==="cancelled";kind:"warning";message:"Search cancelled. Existing results were not replaced."}
        StatusBanner{Layout.fillWidth:true;visible:controller.searchState==="error";kind:"error";message:controller.statusMessage}
        TabBar{id:views;objectName:"resultsViewSwitch";Layout.fillWidth:true;currentIndex:controller.resultsView;Accessible.name:"Results view";onCurrentIndexChanged:controller.saveResultsView(currentIndex);TabButton{text:"List";Accessible.name:"List view"}TabButton{text:"Grid";Accessible.name:"Grid view"}}
        StackLayout{Layout.fillWidth:true;Layout.preferredHeight:220;currentIndex:views.currentIndex
            ListView{id:datesList;model:resultModel;clip:true;activeFocusOnTab:true;Accessible.name:"Matching dates";delegate:ItemDelegate{id:dateRow;required property string date;required property int matchedCount;required property int totalCount;width:ListView.view.width;text:date+"    "+matchedCount+" matched · "+totalCount+" total";highlighted:controller.selectedDate===date;Accessible.name:text;onClicked:controller.selectDate(date);Keys.onReturnPressed:controller.selectDate(date);TapHandler{acceptedButtons:Qt.RightButton;onTapped:dateMenu.popup()}Menu{id:dateMenu;MenuItem{text:"Copy Date";onTriggered:controller.copyText(dateRow.date)}}}}
            GridView{id:resultsGrid;model:resultModel;cellWidth:112;cellHeight:68;clip:true;activeFocusOnTab:true;Accessible.name:"Matching dates grid";delegate:Button{required property string date;required property int matchedCount;width:104;height:60;text:date.slice(5)+"\n"+matchedCount+" matched";Accessible.name:date+", "+matchedCount+" matched events";onClicked:controller.selectDate(date)}}
        }
        Label{text:controller.selectedDate?"Events on "+controller.selectedDate:"Selected-date events";font.bold:true}
        EventTable{visible:eventModel.count>0;Layout.fillWidth:true;Layout.fillHeight:true}
        EmptyState{visible:controller.isLoading;Layout.fillWidth:true;Layout.fillHeight:true;symbol:"◌";title:"Searching calendar";detail:"The database is being read on a dedicated worker thread."}
        EmptyState{visible:!controller.isLoading&&controller.searchState==="zero";Layout.fillWidth:true;Layout.fillHeight:true;symbol:"○";title:"No matching dates";detail:"The search completed successfully. Adjust the filters or rules and run it again."}
        EmptyState{visible:!controller.isLoading&&controller.resultCount===0&&controller.searchState!=="zero"&&controller.searchState!=="error";Layout.fillWidth:true;Layout.fillHeight:true;symbol:controller.databasePath?"⌁":"!";title:controller.databasePath?(ruleModel.count?"Run this search":"Add a rule to begin"):"No database connected";detail:controller.databasePath?"Matching dates and their complete event sets will appear here.":"Choose a compatible SQLite calendar database from the sidebar."}
        EmptyState{visible:!controller.isLoading&&controller.resultCount>0&&controller.selectedDate!==""&&eventModel.count===0;Layout.fillWidth:true;Layout.fillHeight:true;symbol:"○";title:"No events on selected date";detail:"Choose another matching date."}
        Label{visible:true;text:controller.statusMessage;color:DesignTokens.secondaryText;Accessible.name:text}
    }
}
