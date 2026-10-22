"""Export a MakkOS app's menu as com.canonical.dbusmenu so the shell's global menu bar can show it.

GTK4 cannot hand KWin a Wayland appmenu object, so a MakkOS app instead registers
itself with the shell's registrar under window id (WID_BASE | pid). The shell maps the
active window's pid to that entry (see GlobalMenu.endpoint_for_pid). Without a shell
(no registrar on the session bus) nothing is exported and the app keeps its in-window bar.
"""
import os
import gi
from gi.repository import Gio, GLib

WID_BASE = 0x40000000
PATH = '/org/makos/AppMenu'
XML = '''<node><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
<signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
</interface></node>'''
_exports = {}


def flatten(spec):
    """Spec -> {id: (props, [child ids], action)} with root id 0."""
    nodes = {0: ({}, [], None)}
    counter = [0]

    def new(props, action=None):
        counter[0] += 1
        nodes[counter[0]] = (props, [], action)
        return counter[0]
    for title, items in spec:
        top = new({'label': title.replace('_', '__'), 'children-display': 'submenu'})
        nodes[0][1].append(top)
        for item in items:
            if item is None:
                if nodes[top][1] and nodes[nodes[top][1][-1]][0].get('type') != 'separator':
                    nodes[top][1].append(new({'type': 'separator'}))
                continue
            props = {'label': item[0].replace('_', '__')}
            if len(item) > 2 and item[2]:
                props['shortcut'] = [shortcut_tokens(item[2])]
            nodes[top][1].append(new(props, item[1]))
    for ident, (props, kids, _a) in nodes.items():  # drop a trailing separator
        if kids and nodes[kids[-1]][0].get('type') == 'separator':
            kids.pop()
    return nodes


def shortcut_tokens(accel):
    names = {'Primary': 'Control', 'Control': 'Control', 'Shift': 'Shift', 'Alt': 'Alt', 'Super': 'Super'}
    tokens, rest = [], accel
    while rest.startswith('<'):
        close = rest.index('>')
        tokens.append(names.get(rest[1:close].capitalize(), rest[1:close]))
        rest = rest[close + 1:]
    return tokens + [rest]


def variant_props(props):
    out = {}
    for key, value in props.items():
        if key == 'shortcut':
            out[key] = GLib.Variant('aas', value)
        else:
            out[key] = GLib.Variant('s', value)
    return out


class Export:
    def __init__(self, conn, app, spec):
        self.conn, self.app = conn, app
        self.nodes = flatten(spec)
        self.revision = 1
        self.reg_id = conn.register_object(PATH, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], self.call, self.get_prop, None)

    def get_prop(self, _c, _s, _p, _i, name):
        return {'Version': GLib.Variant('u', 3), 'TextDirection': GLib.Variant('s', 'ltr'),
                'Status': GLib.Variant('s', 'normal'), 'IconThemePath': GLib.Variant('as', [])}.get(name)

    def trigger(self, ident):
        action = self.nodes.get(ident, ({}, [], None))[2]
        window = self.app.get_active_window()
        if action and window:
            name = action if '.' in action else 'win.' + action
            GLib.idle_add(lambda: (window.activate_action(name, None), False)[1])

    def call(self, _c, _sender, _path, _iface, method, params, inv):
        args = params.unpack()
        try:
            if method == 'GetLayout':
                parent, depth, names = args
                if parent not in self.nodes:
                    return inv.return_error_literal(Gio.dbus_error_quark(), Gio.DBusError.INVALID_ARGS, 'No such menu item')
                inv.return_value(GLib.Variant('(u(ia{sv}av))', (self.revision, self._layout_tuple(parent, depth, names))))
            elif method == 'GetGroupProperties':
                ids = args[0] or list(self.nodes)
                inv.return_value(GLib.Variant('(a(ia{sv}))', ([(i, variant_props(self.nodes[i][0])) for i in ids if i in self.nodes],)))
            elif method == 'GetProperty':
                value = variant_props(self.nodes.get(args[0], ({}, [], None))[0]).get(args[1], GLib.Variant('s', ''))
                inv.return_value(GLib.Variant('(v)', (value,)))
            elif method == 'Event':
                if args[1] == 'clicked':
                    self.trigger(args[0])
                inv.return_value(None)
            elif method == 'EventGroup':
                for ident, kind, _data, _ts in args[0]:
                    if kind == 'clicked':
                        self.trigger(ident)
                inv.return_value(GLib.Variant('(ai)', ([],)))
            elif method == 'AboutToShow':
                inv.return_value(GLib.Variant('(b)', (False,)))
            elif method == 'AboutToShowGroup':
                inv.return_value(GLib.Variant('(aiai)', ([], [])))
        except Exception as error:  # a broken menu request must never take the app down
            inv.return_error_literal(Gio.dbus_error_quark(), Gio.DBusError.FAILED, str(error))

    def _layout_tuple(self, ident, depth, names):
        props, kids, _a = self.nodes[ident]
        shown = {k: v for k, v in variant_props(props).items() if not names or k in names}
        children = [] if depth == 0 else [GLib.Variant('(ia{sv}av)', self._layout_tuple(k, depth - 1 if depth > 0 else -1, names)) for k in kids]
        return (ident, shown, children)

    def close(self):
        try:
            self.conn.unregister_object(self.reg_id)
        except GLib.Error:
            pass


def export(app, spec):
    """Register the menu with the shell. Returns True only when the shell can show it."""
    if os.environ.get('MAKOS_NO_GLOBAL_MENU') or getattr(app, '_menu_export', None):
        return bool(getattr(app, '_menu_export', None))
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SESSION)
        # theme-and-system-skin: the shell now owns a MakkOS-private registrar name by default (the canonical one makes
        # Wayland-native Qt/GTK3 apps hide their in-window menus, see docs/makos/theme.md); fall back to the canonical name.
        registrar = None
        for name in ('org.makos.AppMenu.Registrar', 'com.canonical.AppMenu.Registrar'):
            if conn.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'NameHasOwner',
                              GLib.Variant('(s)', (name,)), None, Gio.DBusCallFlags.NONE, 800, None).unpack()[0]:
                registrar = name
                break
        if not registrar:
            return False
        item = Export(conn, app, spec)
        conn.call_sync(registrar, '/com/canonical/AppMenu/Registrar', 'com.canonical.AppMenu.Registrar',
                       'RegisterWindow', GLib.Variant('(uo)', (WID_BASE | os.getpid(), PATH)), None, Gio.DBusCallFlags.NONE, 1500, None)
    except GLib.Error:
        return False
    app._menu_export = item
    return True
