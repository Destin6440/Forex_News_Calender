import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    color:DesignTokens.surface;radius:DesignTokens.radius;border.color:DesignTokens.divider
    implicitHeight:layout.implicitHeight+DesignTokens.section*2
    ColumnLayout { id:layout;anchors.fill:parent;anchors.margins:DesignTokens.section;spacing:DesignTokens.spaceLarge
        Label{text:"Additional-event policy";font.bold:true;font.pixelSize:16}
        ComboBox{Layout.fillWidth:true;model:["Allow additional events","Only within counted scope","Exact event set"];currentIndex:["allow","counted_scope","exact"].indexOf(controller.additionalPolicy);Accessible.name:"Additional-event policy";onActivated:controller.setPolicy(currentText)}
        GridLayout{columns:3;Layout.fillWidth:true;columnSpacing:DesignTokens.spaceLarge
            MultiSelect{fieldLabel:"Counted Currency";options:controller.currencies;selectedText:controller.countedCurrencies;Layout.fillWidth:true;onSelectionChanged:value=>controller.setGlobal("counted_currencies",value)}
            MultiSelect{fieldLabel:"Counted Impact";options:controller.impacts;selectedText:controller.countedImpacts;Layout.fillWidth:true;onSelectionChanged:value=>controller.setGlobal("counted_impacts",value)}
            Item{Layout.fillWidth:true}
            ColumnLayout{spacing:DesignTokens.spaceSmall;Label{text:"Minimum events";color:DesignTokens.secondaryText;font.pixelSize:12}TextField{id:minimumField;objectName:"minimumEventsField";text:String(controller.minimumEvents);validator:IntValidator{bottom:0};Accessible.name:"Minimum total events";Layout.fillWidth:true;onEditingFinished:controller.setGlobal("minimum_events",text)}}
            ColumnLayout{spacing:DesignTokens.spaceSmall;Label{text:"Maximum events";color:DesignTokens.secondaryText;font.pixelSize:12}TextField{id:maximumField;objectName:"maximumEventsField";text:controller.maximumEvents<0?"":String(controller.maximumEvents);placeholderText:"No maximum";validator:IntValidator{bottom:0};Accessible.name:"Maximum total events";Layout.fillWidth:true;onEditingFinished:controller.setGlobal("maximum_events",text)}}
        }
    }
}
