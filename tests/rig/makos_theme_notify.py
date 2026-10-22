#!/usr/bin/env python3
"""Notification client for the rig: real org.freedesktop.Notifications calls over the session bus."""
import sys
import time
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION)
loop = GLib.MainLoop()
signals = []


def on_signal(_c, _s, _p, _i, name, params):
    signals.append((name, params.unpack()))


bus.signal_subscribe('org.freedesktop.Notifications', 'org.freedesktop.Notifications', None, '/org/freedesktop/Notifications', None, Gio.DBusSignalFlags.NONE, on_signal)


def call(method, fmt, args, out=None):
    return bus.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications', 'org.freedesktop.Notifications', method,
                         GLib.Variant(fmt, args), GLib.VariantType.new(out) if out else None, Gio.DBusCallFlags.NONE, 3000, None)


def notify(app, summary, body, actions=(), hints=None, timeout=20000, icon='', replaces=0):
    h = {k: v for k, v in (hints or {}).items()}
    return call('Notify', '(susssasa{sv}i)', (app, replaces, icon, summary, body, list(actions), h, timeout), '(u)').unpack()[0]


caps = call('GetCapabilities', '()', (), '(as)').unpack()[0]
info = call('GetServerInformation', '()', (), '(ssss)').unpack()
print('capabilities', caps, 'server', info)
assert 'actions' in caps and 'inline-reply' in caps
V = GLib.Variant
a = notify('Messages', 'Maria', 'Are we still on for lunch? I booked the corner table <b>by the window</b>.', ['default', 'Open', 'inline-reply', 'Reply'],
           {'x-kde-reply-placeholder-text': V('s', 'Reply to Maria'), 'desktop-entry': V('s', 'makos-files')})
b = notify('Disks', 'Backup in progress', 'Copying Documents to the external drive.', [], {'value': V('i', 64), 'desktop-entry': V('s', 'makos-disk-utility')})
c = notify('Calendar', 'Design review in 10 minutes', 'Room 4B · bring the prototype', ['snooze', 'Snooze', 'join', 'Join'], {'desktop-entry': V('s', 'makos-calendar')})
d = notify('System', 'Battery low', 'Plug in the charger soon.', [], {'urgency': V('y', 2)}, timeout=0)
progress = notify('Disks', 'Backup in progress', 'Copying Documents to the external drive.', [], {'value': V('i', 82), 'x-canonical-private-synchronous': V('s', 'bk'), 'desktop-entry': V('s', 'makos-disk-utility')}, replaces=b)
assert progress == b, 'replace keeps the id'
time.sleep(1.5)
call('CloseNotification', '(u)', (999999,))   # unknown id must be harmless
print('ids', a, b, c, d)
# badge counts reach makos.badges inside the shell; the shell itself is checked by the unit tests
time.sleep(1.0)
print('NOTIFY CLIENT PASS')
