import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Button {
    id: control
    property var options: []
    property string selectedText: ""
    signal selectionChanged(string value)
    text: selectedText.length ? selectedText : "Any"
    Accessible.description: "Open to select one or more database values"
    onClicked: popup.open()

    Popup {
        id: popup
        y: control.height + 4
        width: Math.max(240, control.width)
        height: Math.min(320, contentColumn.implicitHeight + 24)
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        function values() {
            return control.selectedText.split(",").map(function(v) { return v.trim() }).filter(Boolean)
        }

        ScrollView {
            anchors.fill: parent
            ColumnLayout {
                id: contentColumn
                width: popup.width - 24
                Button {
                    text: "Clear · Any"
                    Layout.fillWidth: true
                    onClicked: {
                        control.selectionChanged("")
                        popup.close()
                    }
                }
                Repeater {
                    model: control.options
                    CheckBox {
                        required property string modelData
                        text: modelData
                        checked: popup.values().indexOf(modelData) >= 0
                        onToggled: {
                            var selected = popup.values()
                            var index = selected.indexOf(modelData)
                            if (checked && index < 0)
                                selected.push(modelData)
                            else if (!checked && index >= 0)
                                selected.splice(index, 1)
                            selected.sort()
                            control.selectionChanged(selected.join(", "))
                        }
                    }
                }
            }
        }
    }
}
