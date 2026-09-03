import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
ToolBar {
    id: toolbar
    signal saveAsRequested()
    signal exportRequested()
    RowLayout { anchors.fill: parent; anchors.leftMargin: DesignTokens.spaceLarge; anchors.rightMargin: DesignTokens.spaceLarge; spacing: DesignTokens.space
        TextField { id: titleField; objectName: "searchNameField"; text: controller.searchName; placeholderText: "Search name"; Layout.preferredWidth: 300
            Accessible.name: "Search name"; Accessible.description: "Name used when saving this search"; onEditingFinished: controller.setSearchName(text)
        }
        Label { text: controller.resultsCurrent ? "✓ Results current" : controller.resultsStale ? "△ Results stale" : "Edited"; color: controller.resultsStale ? DesignTokens.warning : DesignTokens.secondaryText; Accessible.name: text }
        Item { Layout.fillWidth: true }
        Button { text: "Save"; Accessible.name: text; onClicked: controller.saveSearch() }
        Button { text: "Save As…"; Accessible.name: text; onClicked: toolbar.saveAsRequested() }
        Button { text: "Export"; enabled: controller.resultsCurrent; Accessible.name: "Export current results"; Accessible.description: enabled ? "Export the current result set" : "Run this search before exporting"; onClicked: toolbar.exportRequested() }
        BusyIndicator { running: controller.isLoading; visible: running; Accessible.name: "Search in progress" }
        Button { objectName: "runSearchButton"; text: controller.isLoading ? "Cancel" : "Run Search"; highlighted: true
            Accessible.name: text; Accessible.description: controller.isLoading ? "Cancel the active search" : "Run the current search definition"
            ToolTip.visible: hovered; ToolTip.text: controller.isLoading ? "Cancel (Escape)" : "Run Search (Command-Return)"
            onClicked: controller.isLoading ? controller.cancelSearch() : controller.runSearch()
        }
    }
}
