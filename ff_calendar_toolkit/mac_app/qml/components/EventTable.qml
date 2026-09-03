import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
Rectangle {
    id:table
    color:DesignTokens.surface;radius:DesignTokens.radius;border.color:DesignTokens.divider;clip:true
    property var widths:[74,72,72,220,86,86,86,100,96]
    property var headings:["Time","Currency","Impact","Event","Actual","Forecast","Previous","Source","Match status"]
    Flickable { anchors.fill:parent;contentWidth:896;contentHeight:height;clip:true
        Column { width:896;height:parent.height
            Row { height:34
                Repeater { model:table.headings;Label{required property int index;required property string modelData;width:table.widths[index];height:34;leftPadding:DesignTokens.space;verticalAlignment:Text.AlignVCenter;text:modelData;font.bold:true;color:DesignTokens.secondaryText} }
            }
            Rectangle{width:parent.width;height:1;color:DesignTokens.divider}
            ListView { id:eventList;objectName:"eventTable";width:parent.width;height:parent.height-35;model:eventModel;clip:true;activeFocusOnTab:true;Accessible.name:"Events for selected date"
                delegate:Rectangle { id:eventRow;required property int index;required property string eventKey;required property string currency;required property string impact;required property string name;required property string time;required property string actual;required property string forecast;required property string previous;required property string sourceType;required property bool matched
                    width:ListView.view.width;height:38;color:ListView.isCurrentItem?Qt.rgba(DesignTokens.accent.r,DesignTokens.accent.g,DesignTokens.accent.b,0.16):(index%2?DesignTokens.surface:DesignTokens.window)
                    Accessible.name:(matched?"Matched":"Unmatched")+" event, "+time+", "+currency+", "+impact+", "+name
                    Row { anchors.fill:parent
                        Label{width:table.widths[0];text:time} Label{width:table.widths[1];text:currency;font.bold:true} Label{width:table.widths[2];text:(impact?"◆ ":"○ ")+impact;color:impact==="red"?DesignTokens.error:impact==="orange"?DesignTokens.warning:DesignTokens.secondaryText} Label{width:table.widths[3];text:name;elide:Text.ElideRight} Label{width:table.widths[4];text:actual||"—"} Label{width:table.widths[5];text:forecast||"—"} Label{width:table.widths[6];text:previous||"—"} Label{width:table.widths[7];text:sourceType;elide:Text.ElideRight} Label{width:table.widths[8];text:matched?"✓ Matched":"— Not matched";color:matched?DesignTokens.success:DesignTokens.secondaryText}
                    }
                    TapHandler{acceptedButtons:Qt.LeftButton;onTapped:eventList.currentIndex=index} TapHandler{acceptedButtons:Qt.RightButton;onTapped:eventMenu.popup()}
                    Menu{id:eventMenu;MenuItem{text:"Copy Event Details";onTriggered:controller.copyEventDetails(eventRow.eventKey)}}
                }
            }
        }
        ScrollBar.horizontal:ScrollBar{}
    }
}
