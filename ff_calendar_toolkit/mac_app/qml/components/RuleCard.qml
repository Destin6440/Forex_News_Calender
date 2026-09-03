import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    id: card
    required property string ruleId
    required property string ruleLabel
    required property string ruleMode
    required property string eventName
    required property string nameOperator
    required property string currencies
    required property string impacts
    required property string sources
    required property string timeMode
    required property string earliest
    required property string latest
    required property string rawTime
    required property int minimum
    required property int maximum
    property bool expanded: true
    signal selected(string identifier)
    implicitHeight: content.implicitHeight + DesignTokens.spaceLarge * 2
    radius: DesignTokens.radius; color: DesignTokens.surface; border.color: activeFocus ? DesignTokens.accent : DesignTokens.divider
    activeFocusOnTab: true; Accessible.name: (ruleLabel || eventName || "Unnamed rule") + ", " + ruleMode + " rule"; Accessible.description: expanded ? "Expanded rule editor" : "Collapsed rule. Press Space to expand."
    Keys.onSpacePressed: expanded=!expanded
    TapHandler { acceptedButtons: Qt.LeftButton; onTapped: { card.forceActiveFocus(); card.selected(ruleId) } }
    TapHandler { acceptedButtons: Qt.RightButton; onTapped: ruleMenu.popup() }
    Menu { id: ruleMenu; MenuItem { text: "Duplicate Rule"; onTriggered: controller.duplicateNode(ruleId) } MenuItem { text: "Delete Rule"; onTriggered: controller.removeNode(ruleId) } }
    ColumnLayout { id: content; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: DesignTokens.spaceLarge; spacing: DesignTokens.space
        RowLayout { Layout.fillWidth: true
            ToolButton { text: card.expanded ? "▾" : "▸"; Accessible.name: (card.expanded ? "Collapse" : "Expand") + " rule"; ToolTip.visible: hovered; ToolTip.text: Accessible.name; onClicked: card.expanded=!card.expanded }
            Label { text: ruleMode === "required" ? "● REQUIRED" : ruleMode === "optional" ? "◇ OPTIONAL" : "⊘ EXCLUDED"; font.bold: true; color: ruleMode === "excluded" ? DesignTokens.error : ruleMode === "optional" ? DesignTokens.warning : DesignTokens.success }
            Label { Layout.fillWidth: true; text: ruleLabel || eventName || "Unnamed rule"; font.bold: true; elide: Text.ElideRight }
            ComboBox { model:["required","optional","excluded"]; currentIndex:model.indexOf(ruleMode); Accessible.name:"Rule mode"; onActivated:controller.updateRule(ruleId,"mode",currentText) }
            ToolButton { text:"•••"; Accessible.name:"Rule actions"; ToolTip.visible:hovered; ToolTip.text:Accessible.name; onClicked:ruleMenu.popup() }
        }
        GridLayout { visible: card.expanded; columns: 3; Layout.fillWidth: true; columnSpacing: DesignTokens.spaceLarge; rowSpacing: DesignTokens.space
            Label { text:"Event name"; color:DesignTokens.secondaryText }
            Label { text:"Name operator"; color:DesignTokens.secondaryText }
            Label { text:"Rule label"; color:DesignTokens.secondaryText }
            ComboBox { id:eventNameBox; objectName:"eventNameCombo"; editable:true; model:controller.eventNames; editText:eventName; Layout.fillWidth:true; Accessible.name:"Event name"
                onAccepted:controller.updateRule(ruleId,"name",editText); onActivated:function(index){controller.updateRule(ruleId,"name",model[index])}; onActiveFocusChanged:if(!activeFocus&&editText!==eventName)controller.updateRule(ruleId,"name",editText)
            }
            ComboBox { model:["contains","exact","starts_with","ends_with","regex"]; currentIndex:model.indexOf(nameOperator); Layout.fillWidth:true; Accessible.name:"Name operator"; onActivated:controller.updateRule(ruleId,"nameOperator",currentText) }
            TextField { text:ruleLabel; placeholderText:"Optional label"; Layout.fillWidth:true; Accessible.name:"Rule label"; onEditingFinished:controller.updateRule(ruleId,"label",text) }
            MultiSelect { fieldLabel:"Currency"; options:controller.currencies; selectedText:currencies; Layout.fillWidth:true; onSelectionChanged:value=>controller.updateRule(ruleId,"currencies",value) }
            MultiSelect { fieldLabel:"Impact"; options:controller.impacts; selectedText:impacts; Layout.fillWidth:true; onSelectionChanged:value=>controller.updateRule(ruleId,"impacts",value) }
            MultiSelect { fieldLabel:"Source"; options:controller.sources; selectedText:sources; Layout.fillWidth:true; onSelectionChanged:value=>controller.updateRule(ruleId,"sources",value) }
            ColumnLayout { spacing:DesignTokens.spaceSmall; Label{text:"Time type";color:DesignTokens.secondaryText;font.pixelSize:12} ComboBox{model:["any","timed","clockless"];currentIndex:model.indexOf(timeMode);Accessible.name:"Time type";Layout.fillWidth:true;onActivated:controller.updateRule(ruleId,"timeMode",currentText)} }
            ColumnLayout { spacing:DesignTokens.spaceSmall; Label{text:"Earliest time";color:DesignTokens.secondaryText;font.pixelSize:12} TextField{text:earliest;placeholderText:"HH:MM";Accessible.name:"Earliest time";Layout.fillWidth:true;onEditingFinished:controller.updateRule(ruleId,"earliest",text)} }
            ColumnLayout { spacing:DesignTokens.spaceSmall; Label{text:"Latest time";color:DesignTokens.secondaryText;font.pixelSize:12} TextField{text:latest;placeholderText:"HH:MM";Accessible.name:"Latest time";Layout.fillWidth:true;onEditingFinished:controller.updateRule(ruleId,"latest",text)} }
            ColumnLayout { spacing:DesignTokens.spaceSmall; Label{text:"Clockless label";color:DesignTokens.secondaryText;font.pixelSize:12} TextField{text:rawTime;placeholderText:"Tentative, All Day…";Accessible.name:"Raw clockless label";Layout.fillWidth:true;onEditingFinished:controller.updateRule(ruleId,"rawTime",text)} }
            RowLayout { Layout.columnSpan:2; Label{text:"Occurrences";color:DesignTokens.secondaryText} SpinBox{from:0;to:99;value:minimum;Accessible.name:"Minimum occurrences";onValueModified:controller.updateRule(ruleId,"minimum",value)} Label{text:"to"} SpinBox{from:-1;to:99;value:maximum;editable:true;Accessible.name:"Maximum occurrences, minus one means unlimited";onValueModified:controller.updateRule(ruleId,"maximum",value)} }
        }
    }
}
