import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
ColumnLayout {
    objectName: "databaseStatus"
    spacing: DesignTokens.spaceSmall
    Label { text: "DATABASE"; color: DesignTokens.secondaryText; font.bold: true }
    RowLayout {
        Label { text: controller.databasePath ? "● Connected" : "○ Disconnected"; color: controller.databasePath ? DesignTokens.success : DesignTokens.warning; Accessible.name: text }
        Rectangle { visible: controller.databasePath !== ""; implicitWidth: readOnly.implicitWidth + 12; implicitHeight: readOnly.implicitHeight + 4; radius: 4; color: DesignTokens.surface
            Label { id: readOnly; anchors.centerIn: parent; text: "Read-only"; font.pixelSize: 11 }
        }
    }
    Label {
        Layout.fillWidth: true
        text: controller.databasePath ? controller.databasePath.split(/[\\/]/).pop() : "No database selected"
        elide: Text.ElideMiddle
        ToolTip.visible: pathHover.hovered
        ToolTip.text: controller.databasePath
        HoverHandler { id: pathHover }
    }
    Label { Layout.fillWidth: true; text: controller.databaseSummary; color: DesignTokens.secondaryText; wrapMode: Text.Wrap }
}
