"""Shared plumbing for MakkOS apps: window skeleton, menu bar, actions, dialogs, data paths."""
import os
import re
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib, Gdk
from .. import ui, common

_CSS_DONE = []


def data_dir(*parts):
    """Per-app user data. XDG_DATA_HOME is honoured so tests and the rig stay private."""
    base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'makos'
    return base.joinpath(*parts)


def cache_dir(*parts):
    base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'makos'
    return base.joinpath(*parts)


def atomic_write(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.makos-tmp')
    if isinstance(data, str):
        temp.write_text(data, encoding='utf-8')
    else:
        temp.write_bytes(data)
    temp.chmod(mode)
    temp.replace(path)


def load_css():
    if _CSS_DONE or Gdk.Display.get_default() is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_path(str(Path(__file__).with_name('apps.css')))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    _CSS_DONE.append(provider)


# A menu spec is [(title, [(label, action, accel) | None, ...]), ...]; None starts a new section.
def build_menu(spec):
    root = Gio.Menu()
    for title, items in spec:
        sub, section = Gio.Menu(), Gio.Menu()
        for item in items:
            if item is None:
                sub.append_section(None, section)
                section = Gio.Menu()
            else:
                section.append(item[0], 'win.' + item[1] if '.' not in item[1] else item[1])
        sub.append_section(None, section)
        root.append_submenu(title, sub)
    return root


class AppWindow:
    """A themed window with optional menu bar, body area and status line."""

    def __init__(self, app, title, width, height, menu=None, status=True):
        load_css()
        self.app = app
        self.win = ui.window(app, title, width, height)
        self.actions = {}
        self.outer = ui.box(True)
        self.exported = False
        self.menubar = None
        if menu:
            self.menubar = Gtk.PopoverMenuBar.new_from_model(build_menu(menu))
            self.menubar.add_css_class('app-menubar')
            self.outer.append(self.menubar)
            for _title, items in menu:
                for item in items:
                    if item and len(item) > 2 and item[2] and hasattr(app, 'set_accels_for_action'):
                        name = 'win.' + item[1] if '.' not in item[1] else item[1]
                        app.set_accels_for_action(name, [item[2]])
            try:
                from .. import appmenu
                self.exported = appmenu.export(app, menu)
            except Exception:  # menu export is a convenience; the in-window bar stays as fallback
                self.exported = False
            if self.exported:
                self.menubar.set_visible(False)
        self.body = ui.box(True)
        self.body.set_vexpand(True)
        self.outer.append(self.body)
        self.status = None
        if status:
            bar = ui.box(css='statusbar')
            self.status = Gtk.Label(label='', xalign=0, hexpand=True, ellipsize=3)
            bar.append(self.status)
            self.outer.append(bar)
        self.win.set_child(self.outer)

    def action(self, name, callback, enabled=True):
        act = Gio.SimpleAction.new(name, None)
        act.connect('activate', lambda *_: callback())
        act.set_enabled(enabled)
        self.win.add_action(act)
        self.actions[name] = act
        return act

    def enable(self, name, value):
        if name in self.actions:
            self.actions[name].set_enabled(bool(value))

    def say(self, text):
        if self.status:
            self.status.set_text(text)

    def present(self):
        self.win.present()
        return self


def confirm(parent, title, detail, yes='OK', no='Cancel', callback=None, destructive=False):
    dialog = Gtk.AlertDialog(message=title, detail=detail, buttons=[no, yes], cancel_button=0, default_button=0 if destructive else 1)

    def done(d, result):
        try:
            choice = d.choose_finish(result)
        except GLib.Error:
            return
        if choice == 1 and callback:
            callback()
    dialog.choose(parent, None, done)


def human(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1000


def clock_text(seconds):
    seconds = max(0, int(seconds or 0))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def snapshot_widget(widget, dest):
    """Render a mapped widget to a PNG (used by the rig; never by users)."""
    from gi.repository import Graphene
    paint = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    w, h = widget.get_width(), widget.get_height()
    paint.snapshot(snap, w, h)
    node = snap.to_node()
    rect = Graphene.Rect().init(0, 0, w, h)
    widget.get_native().get_renderer().render_texture(node, rect).save_to_png(str(dest))


SAFE_NAME = re.compile(r'[^\w.\- ]+')


def safe_filename(name, fallback='untitled'):
    name = SAFE_NAME.sub('_', name).strip(' .')[:80]
    return name or fallback


def notify(summary, body, icon='makos-calendar', app_name='VigilOS'):
    """Post a desktop notification (the shell's banner service). Failure is silent."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications', 'org.freedesktop.Notifications', 'Notify',
                      GLib.Variant('(susssasa{sv}i)', (app_name, 0, icon, summary, body, [], {}, 0)), None, Gio.DBusCallFlags.NONE, 1500, None)
    except GLib.Error:
        pass
