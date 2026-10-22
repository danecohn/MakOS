#!/usr/bin/env python3
"""GTK 3 application with a classic GtkMenuBar, for the global-menu coverage test (needs GTK_MODULES=appmenu-gtk-module)."""
import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

win = Gtk.Window(title='GTK3 Menu App')
win.set_default_size(520, 260)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
bar = Gtk.MenuBar()
for title, items in (('File', ['New', 'Open', 'Quit']), ('Edit', ['Copy', 'Paste']), ('Help', ['About'])):
    top = Gtk.MenuItem(label=title)
    menu = Gtk.Menu()
    for it in items:
        menu.append(Gtk.MenuItem(label=it))
    top.set_submenu(menu)
    bar.append(top)
box.pack_start(bar, False, False, 0)
box.pack_start(Gtk.Label(label='GTK 3 window with a GtkMenuBar'), True, True, 0)
win.add(box)
win.connect('destroy', Gtk.main_quit)
win.show_all()
GLib.timeout_add(int(float(sys.argv[1] if len(sys.argv) > 1 else 40) * 1000), Gtk.main_quit)
Gtk.main()
