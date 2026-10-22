"""DBusMenu registrar plus KWin Wayland surface menu endpoints.

Only menus actually exported by clients are displayed. No invented File/Edit actions.
"""
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

class GlobalMenu:
    def __init__(self, conn, container):
        self.conn, self.container = conn, container
        self.windows = {}
        self.endpoint = None
        self.buttons = []
        self.generation = 0
        self.registration = conn.register_object('/com/canonical/AppMenu/Registrar', Gio.DBusNodeInfo.new_for_xml(REGISTRAR).interfaces[0], self.handle, None, None)
        self.owner = Gio.bus_own_name_on_connection(conn, 'com.canonical.AppMenu.Registrar', Gio.BusNameOwnerFlags.NONE, None, None)
        self.subscription = conn.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged',
                                                '/org/freedesktop/DBus', None, Gio.DBusSignalFlags.NONE, self.vanished)
        self.menu_subscription = None

    def vanished(self, _c, _sender, _path, _iface, _signal, params):
        name, old, new = params.unpack()
        if old and not new:
            self.windows = {wid: value for wid, value in self.windows.items() if value[0] != name}
            if self.endpoint and self.endpoint[0] == name:
                self.set_active({})

    def handle(self, conn, sender, path, iface, method, params, invocation):
        values = params.unpack()
        if method == 'RegisterWindow':
            wid, menu = values
            self.windows[wid] = (sender, menu)
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

    def set_active(self, window):
        service, path = window.get('menuService', ''), window.get('menuPath', '')
        endpoint = (service, path) if service and path and path != '/' else None
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
