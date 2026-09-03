import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    color:DesignTokens.surface;radius:DesignTokens.radius;border.color:DesignTokens.divider
    implicitHeight:layout.implicitHeight+DesignTokens.section*2
    ColumnLayout { id:layout;anchors.fill:parent;anchors.margins:DesignTokens.section;spacing:DesignTokens.spaceLarge
        Label{text:"Search scope and global filters";font.bold:true;font.pixelSize:16}
        GridLayout { columns:3;Layout.fillWidth:true;columnSpacing:DesignTokens.spaceLarge;rowSpacing:DesignTokens.space
            ColumnLayout{spacing:DesignTokens.spaceSmall;Label{text:"Start date";color:DesignTokens.secondaryText;font.pixelSize:12}TextField{id:startField;objectName:"startDateField";text:controller.startDate;placeholderText:"YYYY-MM-DD";Accessible.name:"Start date";Layout.fillWidth:true;onEditingFinished:controller.setGlobal("start_date",text)}}
            ColumnLayout{spacing:DesignTokens.spaceSmall;Label{text:"End date";color:DesignTokens.secondaryText;font.pixelSize:12}TextField{id:endField;objectName:"endDateField";text:controller.endDate;placeholderText:"YYYY-MM-DD";Accessible.name:"End date";Layout.fillWidth:true;onEditingFinished:controller.setGlobal("end_date",text)}}
            ColumnLayout{spacing:DesignTokens.spaceSmall;Label{text:"Sort order";color:DesignTokens.secondaryText;font.pixelSize:12}ComboBox{objectName:"resultSortCombo";model:["Newest first","Oldest first"];currentIndex:controller.resultSort==="oldest"?1:0;Accessible.name:"Result sort order";Layout.fillWidth:true;onActivated:controller.setSort(currentText)}}
            MultiSelect{fieldLabel:"Currency";options:controller.currencies;selectedText:controller.globalCurrencies;Layout.fillWidth:true;onSelectionChanged:value=>controller.setGlobal("currencies",value)}
            MultiSelect{fieldLabel:"Impact";options:controller.impacts;selectedText:controller.globalImpacts;Layout.fillWidth:true;onSelectionChanged:value=>controller.setGlobal("impacts",value)}
            MultiSelect{fieldLabel:"Source";options:controller.sources;selectedText:controller.globalSources;Layout.fillWidth:true;onSelectionChanged:value=>controller.setGlobal("source_types",value)}
        }
        Label{text:"Weekdays";color:DesignTokens.secondaryText;font.pixelSize:12}
        RowLayout{Repeater{model:["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];CheckBox{required property int index;required property string modelData;text:modelData;checked:controller.weekdays.indexOf(index)>=0;Accessible.name:modelData+" included";onToggled:controller.toggleWeekday(index,checked)}}}
    }
}
