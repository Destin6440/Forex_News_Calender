import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    id: card
    required property string groupId
    required property string groupOperator
    required property bool expanded
    signal selected(string identifier)
    implicitHeight: row.implicitHeight + DesignTokens.spaceLarge * 2
    radius: DesignTokens.radius; color: DesignTokens.surface; border.color: activeFocus ? DesignTokens.accent : DesignTokens.divider
    activeFocusOnTab:true; Accessible.name:groupOperator+" rule group"; Accessible.description:"Group in the rule hierarchy"
    Keys.onSpacePressed:controller.toggleGroup(groupId)
    TapHandler { acceptedButtons:Qt.LeftButton;onTapped:{card.forceActiveFocus();card.selected(groupId)} }
    TapHandler { acceptedButtons:Qt.RightButton;onTapped:groupMenu.popup() }
    Menu { id:groupMenu; MenuItem{text:"Duplicate Group";onTriggered:controller.duplicateNode(groupId)} MenuItem{text:"Add Rule";onTriggered:controller.addRuleToGroup(groupId)} MenuItem{text:"Add Nested Group";onTriggered:controller.addGroupToGroup(groupId)} MenuSeparator{} MenuItem{text:"Delete Group";onTriggered:controller.removeNode(groupId)} }
    RowLayout { id:row;anchors.fill:parent;anchors.margins:DesignTokens.spaceLarge;spacing:DesignTokens.space
        ToolButton{text:card.expanded?"▾":"▸";Accessible.name:(card.expanded?"Collapse":"Expand")+" group";onClicked:controller.toggleGroup(groupId)}
        Label{text:"⊞ GROUP";font.bold:true;color:DesignTokens.accent}
        ComboBox{model:["AND","OR"];currentIndex:model.indexOf(groupOperator);Accessible.name:"Group operator";onActivated:controller.updateGroup(groupId,currentText)}
        Label{Layout.fillWidth:true;text:groupOperator==="AND"?"All child rules must match":"Any child rule may match";color:DesignTokens.secondaryText}
        ToolButton{text:"+";Accessible.name:"Add child rule";ToolTip.visible:hovered;ToolTip.text:Accessible.name;onClicked:controller.addRuleToGroup(groupId)}
        ToolButton{text:"•••";Accessible.name:"Group actions";ToolTip.visible:hovered;ToolTip.text:Accessible.name;onClicked:groupMenu.popup()}
    }
}
