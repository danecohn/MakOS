"""StatusNotifier watcher/host and GTK4 tray; all remote calls are asynchronous.

Uses org.kde.StatusNotifierItem and com.canonical.dbusmenu. XEmbed-only
legacy icons need an external bridge and are not handled by this Wayland host.
"""
import os
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

WATCHER = 'org.kde.StatusNotifierWatcher'
WATCH_PATH = '/StatusNotifierWatcher'
ITEM = 'org.kde.StatusNotifierItem'
MENU = 'com.canonical.dbusmenu'
XML = '''<node><interface name="org.kde.StatusNotifierWatcher">
 <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
 <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
 <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
 <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
 <property name="ProtocolVersion" type="i" access="read"/>
 <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
 <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
 <signal name="StatusNotifierHostRegistered"/>
 <signal name="StatusNotifierHostUnregistered"/>
</interface></node>'''


def endpoint(service, sender=None):
    """The protocol accepts either a bus name or an object path from the caller."""
    if service.startswith('/'):
        bus, path = sender, service
    else:
        bus, sep, rest = service.partition('/')
        path = '/' + rest if sep else '/StatusNotifierItem'
    if not bus or not Gio.dbus_is_name(bus) or not GLib.Variant.is_object_path(path):
        raise ValueError('Invalid StatusNotifier endpoint')
    return bus, path


def pixmap_rgba(pixmaps, size=20):
    """Choose the nearest useful size and convert network-order ARGB to RGBA.

    Limit allocations from another process; malformed icons fall back to a name.
    """
    valid = [(w, h, data) for w, h, data in pixmaps
             if 0 < w <= 512 and 0 < h <= 512 and len(data) == w * h * 4]
    if not valid:
        return None
    w, h, data = min(valid, key=lambda p: (max(0, size - min(p[0], p[1])), abs(max(p[0], p[1]) - size)))
    raw = bytes(data)
    rgba = bytearray(len(raw))
    rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = raw[1::4], raw[2::4], raw[3::4], raw[0::4]
    return w, h, bytes(rgba)


def call(conn, bus, path, iface, method, params=None, done=None, cancellable=None):
    def finish(source, result):
        try:
            value = source.call_finish(result)
        except GLib.Error as error:
            if done:
                done(None, error)
        else:
            if done:
                done(value, None)
    conn.call(bus, path, iface, method, params, None,
              Gio.DBusCallFlags.NO_AUTO_START, 2500, cancellable, finish)


class Tray(Gtk.Box):
    def __init__(self):
        super().__init__(spacing=2, valign=Gtk.Align.CENTER)
        self.set_tooltip_text('System tray')
        self.conn = None
        self.items = {}
        self._registrations = {}
        self._hosts = {}
        self._external = None
        self._export = 0
        self._owner = 0
        self._closed = False
        self._generation = 0
        self._cancel = Gio.Cancellable()

    def start(self):
        self._owner = Gio.bus_own_name(Gio.BusType.SESSION, WATCHER, Gio.BusNameOwnerFlags.NONE,
                                       self._bus, self._acquired, self._lost)

    def _bus(self, conn, _name):
        self.conn = conn

    def _acquired(self, _conn, _name):
        self._generation += 1
        if self._external:
            for handler in self._external_handlers:
                self._external.disconnect(handler)
            self._external = None
        self._clear()
        if not self._export:
            info = Gio.DBusNodeInfo.new_for_xml(XML)
            self._export = self.conn.register_object(WATCH_PATH, info.interfaces[0], self._method, self._property, None)
        self._signal('StatusNotifierHostRegistered')

    def _lost(self, conn, _name):
        if self._closed or conn is None:
            return
        # Another watcher may already be running. Join it as a host, without
        # replacing it, and continue displaying its registered items.
        self._generation += 1
        generation = self._generation
        if self._export:
            conn.unregister_object(self._export)
            self._export = 0
        self._clear()

        def ready(source, result):
            try:
                proxy = Gio.DBusProxy.new_finish(result)
            except GLib.Error:
                return
            if self._closed or generation != self._generation:
                return
            self._external = proxy
            self._external_handlers = [proxy.connect('g-signal', self._external_signal),
                                       proxy.connect('notify::g-name-owner', self._external_owner)]
            self._join_external()
        Gio.DBusProxy.new(conn, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None, WATCHER, WATCH_PATH,
                          WATCHER, self._cancel, ready)

    def _join_external(self):
        proxy = self._external
        if not proxy or not proxy.get_name_owner():
            return
        call(self.conn, WATCHER, WATCH_PATH, WATCHER, 'RegisterStatusNotifierHost',
             GLib.Variant('(s)', (self.conn.get_unique_name(),)), cancellable=self._cancel)
        prop = proxy.get_cached_property('RegisteredStatusNotifierItems')
        for service in prop.unpack() if prop else []:
            self._external_add(service)

    def _external_owner(self, *_):
        self._clear()
        self._join_external()

    def _external_signal(self, _proxy, _sender, signal, params):
        if signal == 'StatusNotifierItemRegistered':
            self._external_add(params.unpack()[0])
        elif signal == 'StatusNotifierItemUnregistered':
            self._remove(params.unpack()[0])

    def _external_add(self, service):
        try:
            bus, path = endpoint(service)
        except ValueError:
            return
        self._add(bus + path, bus, path)

    def _property(self, _conn, _sender, _path, _iface, name):
        return {'RegisteredStatusNotifierItems': GLib.Variant('as', sorted(self._registrations)),
                'IsStatusNotifierHostRegistered': GLib.Variant('b', True),
                'ProtocolVersion': GLib.Variant('i', 0)}.get(name)

    def _signal(self, name, service=None):
        if self.conn and not self._closed:
            self.conn.emit_signal(None, WATCH_PATH, WATCHER, name,
                                  GLib.Variant('(s)', (service,)) if service is not None else None)

    def _changed(self):
        self.conn.emit_signal(None, WATCH_PATH, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                              GLib.Variant('(sa{sv}as)', (WATCHER, {
                                  'RegisteredStatusNotifierItems': GLib.Variant('as', sorted(self._registrations))}, [])))

    def _method(self, _conn, sender, _path, _iface, method, params, invocation):
        service = params.unpack()[0]
        try:
            bus, path = endpoint(service, sender)
            if method == 'RegisterStatusNotifierHost' and service.startswith('/'):
                raise ValueError('A host must provide a bus name')
        except ValueError as error:
            invocation.return_dbus_error('org.freedesktop.DBus.Error.InvalidArgs', str(error))
            return
        generation = self._generation

        def resolved(value, error):
            if self._closed or generation != self._generation:
                invocation.return_dbus_error('org.freedesktop.DBus.Error.Failed', 'Watcher changed')
                return
            if error or value.unpack()[0] != sender:
                invocation.return_dbus_error('org.freedesktop.DBus.Error.AccessDenied', 'The caller must own the registered service')
                return
            if method == 'RegisterStatusNotifierHost':
                if bus not in self._hosts:
                    self._hosts[bus] = Gio.bus_watch_name_on_connection(self.conn, bus, Gio.BusNameWatcherFlags.NONE,
                                                                       None, lambda *_: self._host_gone(bus))
                    self._signal('StatusNotifierHostRegistered')
            else:
                key = bus + path
                if key not in self._registrations:
                    self._registrations[key] = Gio.bus_watch_name_on_connection(
                        self.conn, bus, Gio.BusNameWatcherFlags.NONE, None, lambda *_: self._unregister(key))
                    self._add(key, bus, path)
                    self._signal('StatusNotifierItemRegistered', key)
                    self._changed()
            invocation.return_value(None)
        call(self.conn, 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner',
             GLib.Variant('(s)', (bus,)), resolved, self._cancel)

    def _host_gone(self, bus):
        watch = self._hosts.pop(bus, 0)
        if watch:
            Gio.bus_unwatch_name(watch)
        # This shell remains a host even when another host leaves.

    def _add(self, key, bus, path):
        if self._closed or key in self.items:
            return
        item = TrayItem(self.conn, bus, path)
        self.items[key] = item
        self.append(item)

    def _remove(self, key):
        item = self.items.pop(key, None)
        if item:
            item.close()
            self.remove(item)

    def _unregister(self, key):
        watch = self._registrations.pop(key, 0)
        if watch:
            Gio.bus_unwatch_name(watch)
            self._remove(key)
            self._signal('StatusNotifierItemUnregistered', key)
            self._changed()

    def _clear(self):
        for key in list(self._registrations):
            Gio.bus_unwatch_name(self._registrations.pop(key))
        for bus in list(self._hosts):
            self._host_gone(bus)
        for key in list(self.items):
            self._remove(key)

    def close(self):
        self._closed = True
        self._generation += 1
        self._cancel.cancel()
        if self._external:
            for handler in self._external_handlers:
                self._external.disconnect(handler)
            self._external = None
        self._clear()
        if self._export:
            self.conn.unregister_object(self._export)
            self._export = 0
        if self._owner:
            Gio.bus_unown_name(self._owner)
            self._owner = 0


class TrayItem(Gtk.Button):
    def __init__(self, conn, bus, path):
        super().__init__()
        self.conn, self.bus, self.path = conn, bus, path
        self.props = {}
        self._cancel = Gio.Cancellable()
        self._closed = False
        self._pending = False
        self._again = False
        self.menu = None
        self.add_css_class('am-bar-icon')
        self.add_css_class('am-tray-icon')
        self.image = Gtk.Image(pixel_size=20)
        self.set_child(self.image)
        self.set_visible(False)
        self.connect('clicked', self._activate)
        gesture = Gtk.GestureClick(button=0)
        gesture.connect('released', self._released)
        self.add_controller(gesture)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES |
                                               Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect('scroll', self._scroll)
        self.add_controller(scroll)
        self._signals = [conn.signal_subscribe(bus, ITEM, None, path, None, Gio.DBusSignalFlags.NONE, self._signal),
                         conn.signal_subscribe(bus, 'org.freedesktop.DBus.Properties', 'PropertiesChanged', path,
                                               None, Gio.DBusSignalFlags.NONE, self._signal)]
        self.refresh()

    def _signal(self, *_):
        self.refresh()

    def refresh(self):
        if self._closed:
            return
        if self._pending:
            self._again = True
            return
        self._pending = True

        def loaded(value, error):
            self._pending = False
            if self._closed:
                return
            if not error:
                self.props = value.unpack()[0]
                self._render()
            if self._again:
                self._again = False
                self.refresh()
        call(self.conn, self.bus, self.path, 'org.freedesktop.DBus.Properties', 'GetAll',
             GLib.Variant('(s)', (ITEM,)), loaded, self._cancel)

    def _render(self):
        p = self.props
        attention = p.get('Status') == 'NeedsAttention'
        self.set_visible(p.get('Status', 'Active') != 'Passive')
        if attention:
            self.add_css_class('attention')
        else:
            self.remove_css_class('attention')
        tip = p.get('ToolTip', ('', [], '', ''))
        self.set_tooltip_text('\n'.join(str(s) for s in tip[2:4] if s) or p.get('Title') or p.get('Id') or self.bus)
        name = (p.get('AttentionIconName') if attention else '') or p.get('IconName', '')
        pixels = (p.get('AttentionIconPixmap') if attention else []) or p.get('IconPixmap', [])
        theme_path = p.get('IconThemePath', '')
        # Per-item theme paths must not pollute the shell's global icon theme.
        icons = Gtk.IconTheme.new()
        icons.set_search_path(list(Gtk.IconTheme.get_for_display(self.get_display()).get_search_path()))
        icons.set_theme_name(Gtk.Settings.get_default().get_property('gtk-icon-theme-name'))
        if theme_path and os.path.isabs(theme_path):
            icons.add_search_path(theme_path)
        if name and os.path.isabs(name) and Path(name).is_file():
            self.image.set_from_file(name)
        elif name and icons.has_icon(name):
            self.image.set_from_paintable(icons.lookup_icon(name, None, 20, self.get_scale_factor(),
                                                          Gtk.TextDirection.NONE, Gtk.IconLookupFlags.FORCE_REGULAR))
        else:
            rgba = pixmap_rgba(pixels)
            if rgba:
                w, h, data = rgba
                self.image.set_from_paintable(Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8A8,
                                                                    GLib.Bytes.new(data), w * 4))
            else:
                self.image.set_from_icon_name('application-x-executable-symbolic')
        menu_path = p.get('Menu', '/')
        if self.menu and self.menu.path != menu_path:
            self.menu.close()
            self.menu = None
        if not self.menu and menu_path != '/' and GLib.Variant.is_object_path(menu_path):
            self.menu = RemoteMenu(self, menu_path)

    def _invoke(self, method, params):
        call(self.conn, self.bus, self.path, ITEM, method, params, cancellable=self._cancel)

    def _activate(self, *_):
        if self.props.get('ItemIsMenu'):
            self.open_menu()
        else:
            call(self.conn, self.bus, self.path, ITEM, 'Activate', GLib.Variant('(ii)', (0, 0)),
                 lambda _value, error: self.open_menu() if error and not self._closed else None, self._cancel)

    def _released(self, gesture, _n, _x, _y):
        button = gesture.get_current_button()
        if button == 3:
            self.open_menu()
        elif button == 2:
            self._invoke('SecondaryActivate', GLib.Variant('(ii)', (0, 0)))

    def _scroll(self, _controller, dx, dy):
        delta, axis = (-dy, 'vertical') if dy else (-dx, 'horizontal')
        self._invoke('Scroll', GLib.Variant('(is)', (int(delta * 120), axis)))
        return True

    def open_menu(self):
        if self.menu:
            self.menu.popup()
        else:
            # Wayland has no client global coordinates; an exported D-Bus menu
            # is preferred. Legacy ContextMenu implementations get (0, 0).
            self._invoke('ContextMenu', GLib.Variant('(ii)', (0, 0)))

    def close(self):
        self._closed = True
        self._cancel.cancel()
        for signal in self._signals:
            self.conn.signal_unsubscribe(signal)
        if self.menu:
            self.menu.close()


class RemoteMenu:
    """Render dbusmenu layouts in a popover anchored to the stable tray button."""
    def __init__(self, item, path):
        self.item, self.path = item, path
        self.conn, self.bus = item.conn, item.bus
        self._cancel = Gio.Cancellable()
        self._closed = False
        self._request = 0
        self._parent = 0
        self._parents = []
        self.pop = Gtk.Popover()
        self.pop.add_css_class('am-panel')
        self.pop.set_parent(item)
        self._signal = self.conn.signal_subscribe(self.bus, MENU, None, path, None,
                                                 Gio.DBusSignalFlags.NONE, self._updated)

    def _call(self, method, params, done=None):
        call(self.conn, self.bus, self.path, MENU, method, params, done, self._cancel)

    def _updated(self, _conn, _sender, _path, _iface, name, _params):
        if name in ('LayoutUpdated', 'ItemsPropertiesUpdated') and self.pop.get_visible():
            self._load(self._parent)

    def popup(self):
        if not self.pop.get_visible():
            # GTK/KWin can reject a rapid remap of the same layer-shell popup
            # ("xdg_surface is already mapped"). Use a fresh native surface
            # for each opening; layout updates retain that open surface.
            self.pop.unparent()
            self.pop = Gtk.Popover()
            self.pop.add_css_class('am-panel')
            self.pop.set_parent(self.item)
        self._parents = []
        self._show(0)
        self.pop.popup()

    def _show(self, parent):
        self._parent = parent
        self._call('AboutToShow', GLib.Variant('(i)', (parent,)),
                   lambda *_: self._load(parent) if not self._closed and self._parent == parent else None)

    def _load(self, parent):
        self._request += 1
        request = self._request

        def loaded(value, error):
            if self._closed or request != self._request:
                return
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            for edge in ('top', 'bottom', 'start', 'end'):
                getattr(col, 'set_margin_' + edge)(8)
            if parent:
                back = Gtk.Button(label='‹ Back')
                back.connect('clicked', lambda *_: self._show(self._parents.pop() if self._parents else 0))
                col.append(back)
            if error:
                col.append(Gtk.Label(label='Menu unavailable'))
            else:
                _revision, layout = value.unpack()
                for node in layout[2][:200]:
                    if isinstance(node, GLib.Variant):
                        node = node.unpack()
                    ident, props, children = node
                    if not props.get('visible', True):
                        continue
                    if props.get('type') == 'separator':
                        col.append(Gtk.Separator())
                        continue
                    label = props.get('label', '').replace('_', '')
                    if props.get('toggle-type') in ('checkmark', 'radio'):
                        label = ('✓ ' if props.get('toggle-state') == 1 else '    ') + label
                    submenu = props.get('children-display') == 'submenu' or bool(children)
                    button = Gtk.Button(label=label + ('  ›' if submenu else ''), use_underline=False)
                    button.add_css_class('am-tray-menu-item')
                    button.set_sensitive(props.get('enabled', True))
                    button.connect('clicked', lambda _b, i=ident, sub=submenu: self._select(i, sub))
                    col.append(button)
                if not col.get_first_child():
                    col.append(Gtk.Label(label='No actions'))
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_min_content_width(180)
            scroller.set_max_content_height(480)
            scroller.set_propagate_natural_height(True)
            scroller.set_child(col)
            self.pop.set_child(scroller)
        self._call('GetLayout', GLib.Variant('(iias)', (parent, 1, [])), loaded)

    def _select(self, ident, submenu):
        if submenu:
            self._parents.append(self._parent)
            self._show(ident)
        else:
            self._call('Event', GLib.Variant('(isvu)', (ident, 'clicked', GLib.Variant('i', 0), 0)))
            self.pop.popdown()

    def close(self):
        self._closed = True
        self._cancel.cancel()
        self.conn.signal_unsubscribe(self._signal)
        self.pop.popdown()
        self.pop.unparent()
