# Protocol references

Consulted 2026-10-22; these describe APIs, not redistributed artwork.

* KWin scripting API: https://develop.kde.org/docs/plasma/kwin/api/
* KWin scripting tutorial: https://develop.kde.org/docs/plasma/kwin/
* GTK4 application menu export: https://docs.gtk.org/gtk4/class.ApplicationWindow.html
* GApplication D-Bus/GMenu export: https://wiki.gnome.org/Projects/GLib/GApplication/DBusAPI
* KWin compositor backend notes: https://community.kde.org/KWin/Hacking/Scene

GTK menu models and DBusMenu are distinct protocols. A client must export a
compatible menu before MakOS can display it. Universal support is a release gate.

KWin ScreenShot2 version 5 defaults to hiding the caller's windows. A shell owns
its desktop and apps, so capture explicitly sets `hide-caller-windows=false`:
https://github.com/KDE/kwin/blob/master/src/plugins/screenshot/org.kde.KWin.ScreenShot2.xml
