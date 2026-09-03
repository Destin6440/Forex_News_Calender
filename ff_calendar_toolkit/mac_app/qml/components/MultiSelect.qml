import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ColumnLayout {
    id: control
    property string fieldLabel: "Values"
    property var options: []
    property string selectedText: ""
    signal selectionChanged(string value)
    spacing: DesignTokens.spaceSmall

    Label { text: control.fieldLabel; color: DesignTokens.secondaryText; font.pixelSize: 12 }
    Button {
        id: button
        Layout.fillWidth: true
        text: control.selectedText.length ? control.selectedText : "Any"
        Accessible.name: control.fieldLabel
        Accessible.description: "Selected value: " + text + ". Open to choose one or more database values."
        ToolTip.visible: hovered && control.selectedText.length > 24
        ToolTip.text: control.selectedText
        onClicked: popup.open()
    }
    Popup {
        id: popup
        parent: button
        y: button.height + DesignTokens.spaceSmall
        width: Math.max(240, button.width)
        height: Math.min(320, contentColumn.implicitHeight + 24)
        modal: true; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        function values() { return control.selectedText.split(",").map(function(v) { return v.trim() }).filter(Boolean) }
        ScrollView {
            anchors.fill: parent
            ColumnLayout {
                id: contentColumn; width: popup.width - 24
                Button { text: "Any " + control.fieldLabel.toLowerCase(); Layout.fillWidth: true; Accessible.name: text
                    onClicked: { control.selectionChanged(""); popup.close() }
                }
                Repeater { model: control.options
                    CheckBox { required property string modelData; text: modelData; checked: popup.values().indexOf(modelData) >= 0
                        Accessible.name: control.fieldLabel + " " + modelData
                        onToggled: {
                            var selected=popup.values(); var index=selected.indexOf(modelData)
                            if (checked && index < 0) selected.push(modelData)
                            else if (!checked && index >= 0) selected.splice(index,1)
                            selected.sort(); control.selectionChanged(selected.join(", "))
                        }
                    }
                }
            }
        }
    }
}
