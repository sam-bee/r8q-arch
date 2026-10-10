import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui

// Deliberately self-contained phone controls. They do not invoke an Omarchy
// menu, power profile, network action, updater, or filesystem operation.
BarWidget {
  id: root
  moduleName: "r8q.launcher"

  property bool keyboardVisible: true

  implicitWidth: controls.implicitWidth
  implicitHeight: controls.implicitHeight

  RowLayout {
    id: controls
    spacing: Style.space(1)
    anchors.fill: parent

    WidgetButton {
      bar: root.bar
      text: "TERM"
      fixedWidth: 58
      fixedHeight: 48
      horizontalMargin: 8
      verticalPadding: 8
      onPressed: Quickshell.execDetached(["foot"])
    }

    WidgetButton {
      bar: root.bar
      text: root.keyboardVisible ? "KB ON" : "KB OFF"
      fixedWidth: 64
      fixedHeight: 48
      horizontalMargin: 8
      verticalPadding: 8
      onPressed: {
        root.keyboardVisible = !root.keyboardVisible
        Quickshell.execDetached([
          "gdbus", "call", "--session",
          "--dest", "sm.puri.OSK0",
          "--object-path", "/sm/puri/OSK0",
          "--method", "sm.puri.OSK0.SetVisible",
          root.keyboardVisible ? "true" : "false"
        ])
      }
    }
  }
}
