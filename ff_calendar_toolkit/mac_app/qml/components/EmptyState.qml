import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
ColumnLayout {
    property string symbol: "○"
    property string title: "Nothing here"
    property string detail: ""
    spacing: DesignTokens.space
    Label { Layout.alignment: Qt.AlignHCenter; text: parent.symbol; font.pixelSize: 28; color: DesignTokens.secondaryText }
    Label { Layout.alignment: Qt.AlignHCenter; text: parent.title; font.bold: true; font.pixelSize: 16 }
    Label { Layout.alignment: Qt.AlignHCenter; Layout.maximumWidth: 360; text: parent.detail; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: DesignTokens.secondaryText }
}
