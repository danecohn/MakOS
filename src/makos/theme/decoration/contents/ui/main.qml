// SPDX-License-Identifier: GPL-3.0-only
import QtQuick
import org.kde.kwin.decoration
Decoration {
    id: root
    alpha: true
    Component.onCompleted: {
        borders.setBorders(1);
        borders.setTitle(30);
        maximizedBorders.setBorders(0);
        maximizedBorders.setTitle(30);
        extendedBorders.setBorders(5);

    }
    Rectangle {
        anchors.fill: parent
        radius: decoration.client.maximized ? 0 : 6
        color: "#e8eaec"
        border.color: decoration.client.active ? "#858c95" : "#a8adb4"
    }
    Rectangle {
        id: title
        x: 1; y: 1; width: parent.width-2; height: 29
        radius: decoration.client.maximized ? 0 : 5
        gradient: Gradient {
            GradientStop { position: 0; color: decoration.client.active ? "#fafafa" : "#f4f4f4" }
            GradientStop { position: 1; color: decoration.client.active ? "#c9ccd0" : "#dedfe1" }
        }
        Text {
            anchors.centerIn: parent
            width: parent.width-180
            text: decoration.client.caption
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            color: decoration.client.active ? "#252a32" : "#92979e"
            font.family: "DejaVu Sans"
            font.pixelSize: 12
            font.bold: true
        }
        Row {
            x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 7
            GlassButton { buttonType: DecorationOptions.DecorationButtonClose; shade: "#ed7164"; glyph: "×" }
            GlassButton { buttonType: DecorationOptions.DecorationButtonMinimize; shade: "#e5bd49"; glyph: "−" }
            GlassButton { buttonType: DecorationOptions.DecorationButtonMaximizeRestore; shade: "#82c26c"; glyph: "+" }
        }
    }
}
