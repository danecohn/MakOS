"""DBusMenu registrar plus KWin Wayland surface menu endpoints.

Only menus actually exported by clients are displayed. No invented File/Edit actions.

Where a window's menu comes from, in priority order (``endpoint_for``):
  1. KWin's per-surface appmenu properties (the KDE appmenu Wayland protocol: KDE/Qt apps with the
     ``kde`` platform theme, anything using plasma-integration).
  2. The registrar (``com.canonical.AppMenu.Registrar``): the exporting process is identified by the
     bus name's Unix PID and matched to the active window's PID. This covers GTK 3 apps with the
     appmenu-gtk-module, Qt apps using the generic DBusMenu platform menubar (qt6ct), Electron/Chromium
     under XWayland, and MakkOS's own apps (window id ``WID_BASE | pid``, see ``makos.appmenu``).
  3. Nothing: the app keeps its in-window menu and the bar shows only the Window menu.
"""
import os
from gi.repository import Gio, GLib, Gtk
from . import ui
from .shell.tray import call, RemoteMenu, MENU

REGISTRAR = '''<node><interface name="com.canonical.AppMenu.Registrar">
<method name="RegisterWindow"><arg type="u" direction="in"/><arg type="o" direction="in"/></method>
<method name="UnregisterWindow"><arg type="u" direction="in"/></method>
<method name="GetMenuForWindow"><arg type="u" direction="in"/><arg type="s" direction="out"/><arg type="o" direction="out"/></method>
<method name="GetMenus"><arg type="a(uso)" direction="out"/></method>
<signal name="WindowRegistered"><arg type="u"/><arg type="s"/><arg type="o"/></signal>
<signal name="WindowUnregistered"><arg type="u"/></signal>
</interface></node>'''

WID_BASE = 0x40000000  # makos.appmenu registers MakkOS apps as WID_BASE | pid
PRIVATE_NAME = 'org.makos.AppMenu.Registrar'
CANONICAL_NAME = 'com.canonical.AppMenu.Registrar'


def registrar_names(env=None):
    env = os.environ if env is None else env
    names = [PRIVATE_NAME]
    if env.get('MAKOS_APPMENU_REGISTRAR', '') == 'canonical':
        names.append(CANONICAL_NAME)
    return names


def pick_endpoint(window, registrations, pids):
    """Pure: choose (service, path) for a KWin window dict. ``registrations`` is {wid: (sender, path)},
    ``pids`` is {sender: pid}. Returns None when the window has no exported menu."""
    service, path = window.get('menuService', ''), window.get('menuPath', '')
    if service and path and path != '/':
        return (service, path)
    pid = window.get('pid') or 0
    if not pid:
        return None
    direct = registrations.get(WID_BASE | pid)
    if direct and direct[1] != '/':
        return tuple(direct)
    for _wid, (sender, menu) in sorted(registrations.items()):
        if pids.get(sender) == pid and menu and menu != '/':
            return (sender, menu)
    return None


class GlobalMenu:
    def __init__(self, conn, container):
        self.conn, self.container = conn, container
        self.windows = {}
        self.pids = {}
        self.last_window = {}
        self.endpoint = None
        self.buttons = []
        self.generation = 0
        self.registration = conn.register_object('/com/canonical/AppMenu/Registrar', Gio.DBusNodeInfo.new_for_xml(REGISTRAR).interfaces[0], self.handle, None, None)
        # Same object, two possible names. Claiming the canonical name makes every Wayland-native Qt/GTK3 client hide its
        # in-window menu bar without exporting anything (verified in the rig), so it is opt-in:
        #   MAKOS_APPMENU_REGISTRAR=canonical   serve XWayland Qt/GTK3/Electron clients (they register by X11 window id)
        self.names = list(registrar_names())
        self.owners = [Gio.bus_own_name_on_connection(conn, name, Gio.BusNameOwnerFlags.NONE, None, None) for name in self.names]
        self.owner = self.owners[0]
        self.subscription = conn.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged',
                                                '/org/freedesktop/DBus', None, Gio.DBusSignalFlags.NONE, self.vanished)
        self.menu_subscription = None

    def vanished(self, _c, _sender, _path, _iface, _signal, params):
        name, old, new = params.unpack()
        if old and not new:
            self.windows = {wid: value for wid, value in self.windows.items() if value[0] != name}
            self.pids.pop(name, None)
            if self.endpoint and self.endpoint[0] == name:
                self.set_active(self.last_window)

    def handle(self, conn, sender, path, iface, method, params, invocation):
        values = params.unpack()
        if method == 'RegisterWindow':
            wid, menu = values
            self.windows[wid] = (sender, menu)
            self.resolve_pid(sender)
            conn.emit_signal(None, path, iface, 'WindowRegistered', GLib.Variant('(uso)', (wid, sender, menu)))
            invocation.return_value(None)
        elif method == 'UnregisterWindow':
            wid = values[0]
            if self.windows.get(wid, (None,))[0] == sender:
                self.windows.pop(wid, None)
                conn.emit_signal(None, path, iface, 'WindowUnregistered', GLib.Variant('(u)', (wid,)))
            invocation.return_value(None)
        elif method == 'GetMenuForWindow':
            invocation.return_value(GLib.Variant('(so)', self.windows.get(values[0], ('', '/'))))
        elif method == 'GetMenus':
            invocation.return_value(GLib.Variant('(a(uso))', ([(wid, *endpoint) for wid, endpoint in self.windows.items()],)))

    def resolve_pid(self, sender):
        """Learn which process owns a registrar entry (async); then re-pick the active window's menu."""
        if sender in self.pids or not sender:
            return

        def done(value, error):
            if error or value is None:
                return
            self.pids[sender] = value.unpack()[0]
            if self.last_window:
                self.set_active(self.last_window)
        self.conn.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                       GLib.Variant('(s)', (sender,)), None, Gio.DBusCallFlags.NONE, 1500, None,
                       lambda c, r: self._pid_reply(c, r, done))

    @staticmethod
    def _pid_reply(conn, result, done):
        try:
            done(conn.call_finish(result), None)
        except GLib.Error as error:
            done(None, error)

    def endpoint_for_pid(self, pid):
        """Menu endpoint exported by a process (MakkOS apps via WID_BASE | pid, or any registrar client)."""
        return pick_endpoint({'pid': pid}, self.windows, self.pids)

    def set_active(self, window):
        self.last_window = window or {}
        endpoint = pick_endpoint(self.last_window, self.windows, self.pids)
        service, path = endpoint if endpoint else ('', '')
        if endpoint == self.endpoint:
            return
        self.endpoint = endpoint
        self.generation += 1
        if self.menu_subscription:
            self.conn.signal_unsubscribe(self.menu_subscription)
            self.menu_subscription = None
        for b in self.buttons:
            b.remote.close()
        self.buttons = []
        ui.clear(self.container)
        if endpoint:
            self.menu_subscription = self.conn.signal_subscribe(service, MENU, 'LayoutUpdated', path, None, Gio.DBusSignalFlags.NONE, lambda *_: self.reload())
            self.reload()

    def reload(self):
        if not self.endpoint:
            return
        service, path = self.endpoint
        generation = self.generation
        def loaded(value, error):
            if generation != self.generation or error:
                return
            for b in self.buttons:
                b.remote.close()
            self.buttons = []
            ui.clear(self.container)
            _revision, root = value.unpack()
            for child in root[2][:30]:
                node = child.unpack() if isinstance(child, GLib.Variant) else child
                ident, props, children = node
                if not props.get('visible', True):
                    continue
                b = Gtk.Button(label=props.get('label', '').replace('_', ''))
                b.conn, b.bus = self.conn, service
                b.remote = RemoteMenu(b, path)
                b.remote.popup = self.popup_for(b.remote, ident)
                b.set_sensitive(props.get('enabled', True))
                b.connect('clicked', lambda _b, remote=b.remote: remote.popup())
                self.container.append(b)
                self.buttons.append(b)
        call(self.conn, service, path, MENU, 'GetLayout', GLib.Variant('(iias)', (0, 1, [])), loaded)

    @staticmethod
    def popup_for(remote, ident):
        def popup():
            if not remote.pop.get_visible():
                remote.pop.unparent()
                remote.pop = Gtk.Popover()
                remote.pop.set_parent(remote.item)
            remote._parents = []
            remote._show(ident)
            remote.pop.popup()
        return popup
