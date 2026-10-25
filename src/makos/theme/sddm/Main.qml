import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root
    width: 1600; height: 900
    property bool busy: false
    property string errorMessage: ""
    function login() {
        if (busy || !username.text.length) return
        busy = true; errorMessage = ""
        sddm.login(username.text, password.text, sessions.currentIndex)
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#eaf0f5" }
            GradientStop { position: .5; color: "#c9d6e2" }
            GradientStop { position: 1; color: "#9baebb" }
        }
    }
    Column {
        anchors.centerIn: parent; width: 360; spacing: 18
        Image {
            anchors.horizontalCenter: parent.horizontalCenter
            source: "blossom.svg"; width: 110; height: 110
            sourceSize.width: 220; sourceSize.height: 220
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Makk OS"; color: "#253c50"; font.pixelSize: 40; font.weight: Font.Light
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Artemis Softworks LLC"; color: "#4c6375"; font.pixelSize: 15
        }
        TextField {
            id: username; width: parent.width
            text: userModel.lastUser; placeholderText: "User name"
            font.pixelSize: 18; Accessible.name: "User name"
            KeyNavigation.tab: password
            onAccepted: password.forceActiveFocus()
        }
        TextField {
            id: password; width: parent.width
            placeholderText: "Password"; echoMode: TextInput.Password
            font.pixelSize: 18; Accessible.name: "Password"
            enabled: !root.busy; onAccepted: root.login()
            KeyNavigation.tab: sessions
        }
        ComboBox {
            id: sessions; width: parent.width; model: sessionModel
            textRole: "name"; currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
            font.pixelSize: 16; Accessible.name: "Desktop session"
            KeyNavigation.tab: signIn
        }
        Button {
            id: signIn; width: parent.width; text: root.busy ? "Signing in…" : "Log In"
            font.pixelSize: 18; enabled: !root.busy; onClicked: root.login()
            KeyNavigation.tab: username
        }
        Label {
            width: parent.width; text: root.errorMessage
            horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
            color: "#8c244b"; font.pixelSize: 16
            Accessible.role: Accessible.AlertMessage
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; spacing: 16
            Button { text: "Restart"; visible: sddm.canReboot; onClicked: sddm.reboot() }
            Button { text: "Shut Down"; visible: sddm.canPowerOff; onClicked: sddm.powerOff() }
        }
    }
    Connections {
        target: sddm
        function onLoginFailed() {
            root.busy = false; root.errorMessage = "Login failed. Check your user name and password."
            password.text = ""; password.forceActiveFocus()
        }
    }
    Component.onCompleted: password.forceActiveFocus()
}
