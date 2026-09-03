import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
ColumnLayout {
    id:builder
    signal selected(string identifier)
    spacing:DesignTokens.spaceLarge
    RowLayout{Layout.fillWidth:true;Label{text:"Rule expression";font.bold:true;font.pixelSize:18}Label{text:"Nested groups are evaluated from the outside in.";color:DesignTokens.secondaryText}Item{Layout.fillWidth:true}ComboBox{model:["AND","OR"];currentIndex:model.indexOf(controller.rootOperator);Accessible.name:"Root group operator";onActivated:controller.setRootOperator(currentText)}}
    ListView { id:ruleList;objectName:"ruleList";Layout.fillWidth:true;implicitHeight:Math.max(120,contentHeight);model:ruleModel;interactive:false;spacing:DesignTokens.space;currentIndex:count>0?0:-1
        Accessible.name:"Rule hierarchy"
        delegate:Loader { id:delegateLoader
            required property string ruleId;required property string label;required property string mode;required property string name;required property string nameOperator;required property string currencies;required property string impacts;required property string sources;required property string timeMode;required property string earliest;required property string latest;required property string rawTime;required property int minimum;required property int maximum;required property int depth;required property string groupOperator;required property var expanded
            x:Math.min(depth*18,108);width:ListView.view.width-x;sourceComponent:groupOperator!==""?groupDelegate:ruleDelegate
            height:item?item.implicitHeight:0
            Component{id:groupDelegate;RuleGroupCard{width:delegateLoader.width;groupId:delegateLoader.ruleId;groupOperator:delegateLoader.groupOperator;expanded:delegateLoader.expanded===true;onSelected:identifier=>builder.selected(identifier)}}
            Component{id:ruleDelegate;RuleCard{width:delegateLoader.width;ruleId:delegateLoader.ruleId;ruleLabel:delegateLoader.label;ruleMode:delegateLoader.mode;eventName:delegateLoader.name;nameOperator:delegateLoader.nameOperator;currencies:delegateLoader.currencies;impacts:delegateLoader.impacts;sources:delegateLoader.sources;timeMode:delegateLoader.timeMode;earliest:delegateLoader.earliest;latest:delegateLoader.latest;rawTime:delegateLoader.rawTime;minimum:delegateLoader.minimum;maximum:delegateLoader.maximum;onSelected:identifier=>builder.selected(identifier)}}
        }
    }
    EmptyState{visible:ruleModel.count===0;Layout.fillWidth:true;Layout.preferredHeight:130;symbol:"⌁";title:"Build a rule expression";detail:"Add a required, optional, or excluded event rule. Use groups for nested AND/OR logic."}
    RowLayout{Button{text:"＋ Add Rule";Accessible.name:"Add rule";onClicked:controller.addRule()}Button{text:"⊞ Add Group";Accessible.name:"Add nested group";onClicked:controller.addGroup()}Item{Layout.fillWidth:true}Button{text:"Clear";Accessible.name:"Clear search definition";onClicked:controller.newSearch()}}
}
