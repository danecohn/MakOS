// SPDX-License-Identifier: GPL-3.0-only
// MakkOS Glass & Metal window frame: brushed-metal title bar, left glass orbs, soft shadow.
// States: active/inactive, tool (no min/zoom -> compact bar), modal sheet/dialog, maximized,
// edge-tiled (flat corners on the screen-edge sides), HiDPI (vector + @2x bitmaps).
import QtQuick
import org.kde.kwin.decoration
Decoration {
    id: root
    alpha: true
    readonly property var win: decoration.client
    readonly property bool active: win.active
    readonly property bool flat: win.maximized
    readonly property int edges: win.adjacentScreenEdges
    // KWin exposes no window type to decorations; a closeable window that can neither
    // minimise nor maximise is a utility/tool palette or a dialog.
    readonly property bool tool: win.closeable && !win.minimizeable && !win.maximizeable && !win.modal
    readonly property bool sheet: win.modal
    readonly property int titleHeight: tool ? 22 : 30
    readonly property int pad: flat ? 0 : (active ? 14 : 10)
    readonly property color edgeColor: sheet ? "#857380" : (active ? "#a99aa5" : "#d9ccd4")
    property bool groupHover: orbs.hovered
    function corner(a, b) { return (flat || (edges & a) || (edges & b)) ? 0 : 12 }

    Component.onCompleted: {
        borders.setBorders(1);
        borders.setTitle(titleHeight);
        maximizedBorders.setBorders(0);
        maximizedBorders.setTitle(titleHeight);
        extendedBorders.setBorders(5);
        padding.setBorders(14);
    }
    onTitleHeightChanged: { borders.setTitle(titleHeight); maximizedBorders.setTitle(titleHeight) }

    Item {
        id: frame
        x: flat ? 0 : root.padding.left
        y: flat ? 0 : root.padding.top
        width: root.width - (flat ? 0 : root.padding.left + root.padding.right)
        height: root.height - (flat ? 0 : root.padding.top + root.padding.bottom)

        // soft shadow: stacked translucent rounded rectangles (cheap, no shader dependencies)
        Repeater {
            model: flat ? 0 : 7
            Rectangle {
                readonly property int grow: index * 2
                x: -grow; y: -grow + 4 + (root.active ? 2 : 0)
                width: frame.width + grow * 2; height: frame.height + grow * 2
                radius: 7 + grow
                color: "#000000"
                opacity: (root.active ? 0.075 : 0.04) * (1 - index / 8)
            }
        }

        Rectangle {  // window body
            anchors.fill: parent
            topLeftRadius: corner(Qt.TopEdge, Qt.LeftEdge)
            topRightRadius: corner(Qt.TopEdge, Qt.RightEdge)
            bottomLeftRadius: corner(Qt.BottomEdge, Qt.LeftEdge)
            bottomRightRadius: corner(Qt.BottomEdge, Qt.RightEdge)
            color: "#f6f1f4"
            border.width: flat ? 0 : 1
            border.color: root.edgeColor
        }
        Rectangle {  // title bar
            id: title
            x: flat ? 0 : 1; y: flat ? 0 : 1
            width: parent.width - (flat ? 0 : 2); height: root.titleHeight - (flat ? 0 : 1)
            topLeftRadius: Math.max(0, corner(Qt.TopEdge, Qt.LeftEdge) - 1)
            topRightRadius: Math.max(0, corner(Qt.TopEdge, Qt.RightEdge) - 1)
            clip: true
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.active ? "#fbf7f9" : "#f6f1f4" }
                GradientStop { position: 0.5; color: root.active ? "#f8f2f5" : "#f4eef1" }
                GradientStop { position: 0.52; color: root.active ? "#f3ecf0" : "#f2ecef" }
                GradientStop { position: 1.0; color: root.active ? "#efe7ec" : "#f0eaee" }
            }
            Image {  // brushed metal grain (original, generated; contents/images/metal*.png)
                anchors.fill: parent
                source: "../images/metal.png"
                fillMode: Image.Tile
                opacity: 0; visible: false
            }
            Rectangle { x: 0; y: 0; width: parent.width; height: 1; color: "#ffffff"; opacity: 0.9 }
            Rectangle { x: 0; y: parent.height - 1; width: parent.width; height: 1; color: root.edgeColor; opacity: 0.9 }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.max(0, parent.width - 2 * (orbs.width + 24))
                text: win.caption
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideMiddle
                color: root.active ? "#17101a" : "#5d4e5a"
                style: Text.Normal
                font.family: "Vigil Sans"
                font.pixelSize: root.tool ? 11 : 12
                font.bold: root.active
            }
            Row {
                id: orbs
                property bool hovered: hover.hovered
                x: root.tool ? 7 : 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: root.tool ? 5 : 7
                HoverHandler { id: hover }
                GlassButton { kind: "close"; glyph: "×"; active: root.active; groupHover: orbs.hovered; diameter: root.tool ? 12 : 14
                    buttonType: DecorationOptions.DecorationButtonClose; visible: win.closeable }
                GlassButton { kind: "minimize"; glyph: "−"; active: root.active; groupHover: orbs.hovered; diameter: root.tool ? 12 : 14
                    buttonType: DecorationOptions.DecorationButtonMinimize; visible: win.minimizeable }
                GlassButton { kind: "zoom"; glyph: win.maximized ? "−" : "+"; active: root.active; groupHover: orbs.hovered; diameter: root.tool ? 12 : 14
                    buttonType: DecorationOptions.DecorationButtonMaximizeRestore; visible: win.maximizeable }
            }
        }
    }
}
