// SPDX-License-Identifier: GPL-3.0-only
// One orb: pre-rendered original gel art (contents/images/orb-*.png and @2x), glyph drawn on hover of the group.
import QtQuick
import org.kde.kwin.decoration
DecorationButton {
    id: control
    property string kind: "close"      // close | minimize | zoom
    property string glyph: ""
    property bool active: true
    property bool groupHover: false
    property int diameter: 14
    width: diameter; height: diameter
    opacity: enabled ? 1 : 0.45
    Image {
        anchors.fill: parent
        smooth: true
        mipmap: true
        source: "../images/orb-" + control.kind + "-" + (control.active ? (control.pressed ? "pressed" : "active") : (control.groupHover || control.hovered ? "active" : "inactive")) + ".png"
    }
    Text {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: control.kind === "close" ? 0 : -0.5
        visible: control.groupHover || control.hovered
        text: control.glyph
        color: "#3a2a26"
        opacity: 0.78
        font.family: "DejaVu Sans"
        font.bold: true
        font.pixelSize: Math.round(control.diameter * 0.82)
    }
}
