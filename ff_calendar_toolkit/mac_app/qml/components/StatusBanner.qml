import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    id: banner
    property string kind: "info"
    property string message: ""
    property string symbol: kind === "error" ? "!" : kind === "warning" ? "△" : kind === "success" ? "✓" : "i"
    visible: message.length > 0
    implicitHeight: row.implicitHeight + DesignTokens.spaceLarge * 2
    radius: DesignTokens.radius
    property color semanticColor: kind === "error" ? DesignTokens.error : kind === "warning" ? DesignTokens.warning : kind === "success" ? DesignTokens.success : DesignTokens.accent
    color: Qt.rgba(semanticColor.r, semanticColor.g, semanticColor.b, 0.13)
    Accessible.name: message
    Accessible.role: Accessible.StaticText
    RowLayout { id: row; anchors.fill: parent; anchors.margins: DesignTokens.spaceLarge; spacing: DesignTokens.space
        Label { text: banner.symbol; font.bold: true; color: kind === "error" ? DesignTokens.error : kind === "warning" ? DesignTokens.warning : DesignTokens.accent }
        Label { text: banner.message; Layout.fillWidth: true; wrapMode: Text.Wrap }
    }
}
