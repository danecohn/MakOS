// SPDX-License-Identifier: GPL-3.0-only
import QtQuick
import org.kde.kwin.decoration
DecorationButton {
    id: control
    property color shade
    property string glyph
    width: 15; height: 15
    Rectangle {
        anchors.fill: parent
        radius: 8
        border.width: 1
        border.color: "#777d85"
        gradient: Gradient {
            GradientStop { position: 0; color: "#ffffff" }
            GradientStop { position: .42; color: decoration.client.active ? Qt.lighter(control.shade,1.2) : "#d8dade" }
            GradientStop { position: .55; color: decoration.client.active ? Qt.darker(control.shade,1.05) : "#b9bec4" }
            GradientStop { position: 1; color: decoration.client.active ? Qt.lighter(control.shade,1.35) : "#e3e5e8" }
        }
        Text {
            anchors.centerIn: parent
            visible: control.hovered
            text: control.glyph
            color: "#30363b"
            font.pixelSize: 11
        }
    }
}
