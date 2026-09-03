import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    id: sidebar
    objectName: "navigationSidebar"
    property real userWidth: controller.sidebarWidth
    signal renameRequested(string oldName)
    color: DesignTokens.sidebar
    border.color: DesignTokens.divider
    implicitWidth: userWidth

    ColumnLayout { anchors.fill: parent; anchors.margins: DesignTokens.spaceLarge; spacing: DesignTokens.space
        Label { text: "FOREX CALENDAR LAB"; color: DesignTokens.accent; font.bold: true }
        Button { Layout.fillWidth: true; text: "＋ New Search"; Accessible.name: "New Search"; onClicked: controller.newSearch() }
        Label { text: "SAVED SEARCHES"; color: DesignTokens.secondaryText; font.bold: true; font.pixelSize: 12 }
        ListView { id: savedList; objectName: "savedSearchList"; Layout.fillWidth: true; Layout.fillHeight: true; model: savedSearchModel; clip: true; activeFocusOnTab: true
            Accessible.name: "Saved searches"; keyNavigationEnabled: true
            delegate: ItemDelegate { id: savedRow; required property int index; required property string name; width: ListView.view.width; text: name; highlighted: ListView.isCurrentItem
                Accessible.name: "Saved search " + name; Accessible.description: "Press Return to load. Open the context menu for more actions."
                onClicked: { savedList.currentIndex=index; controller.loadSearch(name) }
                Keys.onReturnPressed: controller.loadSearch(name)
                TapHandler { acceptedButtons: Qt.RightButton; onTapped: savedMenu.popup() }
                Menu { id: savedMenu
                    MenuItem { text: "Rename…"; onTriggered: sidebar.renameRequested(savedRow.name) }
                    MenuItem { text: "Duplicate"; onTriggered: controller.duplicateSearch(savedRow.name, savedRow.name + " Copy") }
                    MenuItem { text: "Export JSON…"; onTriggered: controller.exportSavedSearch(savedRow.name) }
                    MenuSeparator {}
                    MenuItem { text: "Delete…"; onTriggered: controller.deleteSearch(savedRow.name) }
                }
            }
            EmptyState { anchors.centerIn: parent; visible: savedList.count === 0; symbol: "☆"; title: "No saved searches"; detail: "Save the current definition to see it here." }
        }
        DatabaseStatus { Layout.fillWidth: true }
        RowLayout { Layout.fillWidth: true
            Button { text: "Choose…"; Accessible.name: "Choose database"; onClicked: controller.chooseDatabase() }
            Button { text: "↻"; enabled: controller.databasePath !== ""; Accessible.name: "Refresh database"; ToolTip.visible: hovered; ToolTip.text: Accessible.name; onClicked: controller.refreshDatabase() }
            Button { text: "⌕"; enabled: controller.databasePath !== ""; Accessible.name: "Reveal database in Finder"; ToolTip.visible: hovered; ToolTip.text: Accessible.name; onClicked: controller.revealDatabase() }
        }
    }
    Rectangle { id: resizeHandle; objectName: "sidebarResizeHandle"; anchors.right: parent.right; width: 6; height: parent.height; color: drag.hovered || resizeDrag.active ? DesignTokens.accent : "transparent"
        HoverHandler { id: drag; cursorShape: Qt.SplitHCursor }
        DragHandler { id: resizeDrag; property real startingWidth: sidebar.userWidth; target: null; xAxis.enabled: true
            onTranslationChanged: sidebar.userWidth=Math.max(190,Math.min(420,startingWidth+translation.x)); onActiveChanged: { if (active) startingWidth=sidebar.userWidth; else controller.saveSidebarState(true,Math.round(sidebar.userWidth)) }
        }
        Accessible.name: "Resize sidebar"
    }
}
