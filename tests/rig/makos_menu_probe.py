#!/usr/bin/env python3
"""Print what the shell's AppMenu registrar currently holds (window id, owner pid, menu path)."""
import json
import sys
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION)
reply, used = None, None
for name in ('org.makos.AppMenu.Registrar', 'com.canonical.AppMenu.Registrar'):
    try:
        reply = bus.call_sync(name, '/com/canonical/AppMenu/Registrar', 'com.canonical.AppMenu.Registrar', 'GetMenus',
                              None, GLib.VariantType.new('(a(uso))'), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        used = name
        if reply:
            break
    except GLib.Error:
        continue
if reply is None:
    print(json.dumps({'registrar': 'unreachable'}))
    sys.exit(1)
rows = []
for wid, sender, path in reply:
    pid = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                        GLib.Variant('(s)', (sender,)), GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
    rows.append({'wid': wid, 'pid': pid, 'path': path})
print(json.dumps({'registrar': used, 'entries': rows}))
