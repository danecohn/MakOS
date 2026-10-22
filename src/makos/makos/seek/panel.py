"""Seek's GTK panel: search field, grouped results, preview pane, keyboard navigation and the Quick Look hook.

Integration with the shell (kept deliberately small): the shell calls `open_seek(shell, applications_only)` from its `seek()`
action and `install_bar_field(shell, row)` once while building the menu bar. The panel only uses these shell members:
new_overlay(title), close_overlay(), launch(app_id), open_file(path), clipboard(text) - each looked up defensively.
"""
import importlib
import os
import threading
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Graphene, Gtk  # noqa: E402

from .. import ui  # noqa: E402
from . import engine as eng  # noqa: E402
from . import index as indexmod  # noqa: E402
from . import providers as P  # noqa: E402

KEYS_HINT = '↑ ↓ select   ⏎ open   Ctrl ⏎ show in Files   Ctrl+Y preview   Esc close'
IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp', 'image/svg+xml')


def _engine(shell):
    e = getattr(shell, '_seek_engine', None)
    if e is None:
        e = shell._seek_engine = eng.Engine()
        if os.environ.get('MAKOS_NO_INDEXER') != '1':
            shell._seek_indexer = indexmod.spawn()  # low-priority separate process; exits with the shell. Cheap, so always started.
    return e


def quicklook(shell, path):
    """Ask the Files package for its previewer; returns True when it handled the request. Every failure is swallowed so a
    missing or changed Files API can never break Seek."""
    try:
        files = importlib.import_module('makos.files')
        fn = getattr(files, 'preview', None)
        if callable(fn) and path and Path(path).is_file() and not indexmod.is_excluded(path):
            fn(shell, str(path))
            return True
    except Exception as error:  # noqa: BLE001
        print('seek: Quick Look unavailable:', type(error).__name__, flush=True)
    return False


def perform(shell, result, reveal=False):
    kind = result.action[0] if result.action else 'none'
    arg = result.action[1] if len(result.action) > 1 else None
    close = getattr(shell, 'close_overlay', None)
    if close:
        close()
    if kind == 'launch':
        shell.launch(arg)
    elif kind == 'pane':
        from ..settings import Settings
        Settings(shell, start=arg)
    elif kind == 'open':
        if reveal:
            from ..apps import launch
            launch(shell, 'files', Path(arg).parent)
        else:
            shell.open_file(arg)
    elif kind == 'copy':
        shell.clipboard(arg)
    elif kind == 'url':
        context = Gio.AppLaunchContext()
        context.unsetenv('LD_PRELOAD')
        try:
            Gio.AppInfo.launch_default_for_uri(arg, context)
        except GLib.Error:
            ui.message(shell, 'Seek', 'No web browser could be opened.')


class SeekPanel:
    def __init__(self, shell, applications_only=False, initial=''):
        self.shell, self.only = shell, applications_only
        self.engine = _engine(shell)
        self.generation = 0
        self.rows, self.selected = [], -1
        self.moved = False  # True once the user navigated with the keyboard or mouse; until then the top hit stays selected
        self.results = []
        w = shell.new_overlay('Seek')
        self.window = w
        panel = ui.box(True, 10, 'seek-sheet')
        panel.set_size_request(780, -1)
        head = ui.box(spacing=12)
        head.append(ui.icon('seek', 32))
        self.entry = Gtk.SearchEntry(hexpand=True, placeholder_text='Search applications' if applications_only else 'Search this computer')
        head.append(self.entry)
        close = ui.button('×', shell.close_overlay)
        close.set_tooltip_text('Close search (Escape)')
        head.append(close)
        panel.append(head)
        body = ui.box(spacing=12)
        self.list = ui.box(True, 0)
        self.scroller = ui.scroll(self.list)
        self.scroller.set_size_request(430, 380)
        body.append(self.scroller)
        self.preview = ui.box(True, 8)
        self.preview.set_size_request(300, 380)
        body.append(self.preview)
        panel.append(body)
        self.hint = Gtk.Label(label=KEYS_HINT, xalign=0, css_classes=['subtitle'])
        panel.append(self.hint)
        self.status = Gtk.Label(label='', xalign=0, css_classes=['subtitle'], wrap=True)
        panel.append(self.status)
        w.set_child(panel)
        self.entry.connect('stop-search', lambda *_: shell.close_overlay())
        self.entry.connect('search-changed', self.changed)
        self.entry.connect('activate', lambda *_: self.activate())
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.key)
        self.entry.add_controller(keys)
        if initial:
            self.entry.set_text(initial)
            self.entry.set_position(-1)
        self.changed()
        w.present()
        self.entry.grab_focus()
        self.show_status()

    # ---- searching
    def changed(self, *_):
        self.generation += 1
        gen = self.generation
        self.moved = False
        text = self.entry.get_text()
        results = self.engine.fast(text, self.only)
        if not text.strip():
            results = self.engine.recents() if not self.only else []
        self.results = list(results)
        self.render()
        if text.strip() and not self.only:
            self.results += self.engine.web(text)
            self.render(keep=True)

            def work():
                return self.engine.slow(text), self.engine.status()

            def done(value):
                found, status = value
                if gen == self.generation and getattr(self.shell, 'overlay', True):
                    self.results += found
                    self.render(keep=True)
                    self.show_status(status)
            self._async(work, done, ([], None))

    @staticmethod
    def _async(fn, done, default=None):
        def run():
            try:
                value = fn()
            except Exception as error:  # noqa: BLE001
                print('seek: search provider failed:', type(error).__name__, flush=True)
                value = [] if default is None else default
            GLib.idle_add(lambda: (done(value), False)[1])
        threading.Thread(target=run, daemon=True).start()

    def show_status(self, st=None):
        if st is None:
            self._async(self.engine.status, self.show_status, None)  # may run a probe subprocess: never on the GTK thread
            return
        if not isinstance(st, dict):
            return
        parts = ['Files: ' + {'LocalSearch': 'LocalSearch index', 'index': f"Seek index ({st['indexed']} files)", 'basic': 'basic name search (building index…)'}[st['files']]]
        if not st['dictionary']:
            parts.append('Dictionary: not installed (install wordnet to enable)')
        self.status.set_text('   •   '.join(parts))

    # ---- rendering
    def render(self, keep=False):
        previous = self.current()
        ui.clear(self.list)
        self.rows = []
        groups = eng.grouped(self.results)
        for group, items in groups:
            self.list.append(Gtk.Label(label=group.upper(), xalign=0, css_classes=['seek-group']))
            for r in items:
                self.list.append(self._row(r))
        if not self.rows:
            self.list.append(Gtk.Label(label='No results' if self.entry.get_text().strip() else 'Type to search', xalign=0, css_classes=['subtitle'], margin_start=8, margin_top=8))
        idx = 0
        if keep and previous and self.moved:
            idx = next((i for i, (r, _w) in enumerate(self.rows) if r.action == previous.action and r.group == previous.group), 0)
        self.select(idx if self.rows else -1)

    def _row(self, r):
        line = ui.box(spacing=10, css='seek-row')
        line.append(ui.icon(r.icon, 28))
        text = ui.box(True, 0)
        text.set_hexpand(True)
        title = Gtk.Label(label=r.title, xalign=0, ellipsize=3, max_width_chars=44)
        text.append(title)
        if r.subtitle:
            text.append(Gtk.Label(label=r.subtitle, xalign=0, ellipsize=3, max_width_chars=52, css_classes=['subtitle']))
        line.append(text)
        click = Gtk.GestureClick()
        n = len(self.rows)
        click.connect('pressed', lambda _g, count, _x, _y, n=n: (setattr(self, 'moved', True), self.select(n), self.activate() if count >= 2 else None))
        line.add_controller(click)
        self.rows.append((r, line))
        return line

    def current(self):
        return self.rows[self.selected][0] if 0 <= self.selected < len(self.rows) else None

    def select(self, i):
        for _r, w in self.rows:
            w.remove_css_class('selected')
        self.selected = i if self.rows and 0 <= i < len(self.rows) else -1
        if self.selected >= 0:
            w = self.rows[self.selected][1]
            w.add_css_class('selected')
            GLib.idle_add(self._scroll_to, w)
        self.show_preview(self.current())

    def _scroll_to(self, w):
        adj = self.scroller.get_vadjustment()
        ok, point = w.compute_point(self.list, Graphene.Point().init(0, 0))
        if ok:
            top, height = point.y, w.get_height()
            if top < adj.get_value():
                adj.set_value(top - 24)
            elif top + height > adj.get_value() + adj.get_page_size():
                adj.set_value(top + height - adj.get_page_size() + 8)
        return False

    # ---- keyboard
    def key(self, _c, keyval, _code, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down, Gdk.KEY_Up, Gdk.KEY_KP_Up, Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):
            self.moved = True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self.select(min(self.selected + 1, len(self.rows) - 1))
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            self.select(max(self.selected - 1, 0))
        elif keyval == Gdk.KEY_Page_Down:
            self.select(min(self.selected + 5, len(self.rows) - 1))
        elif keyval == Gdk.KEY_Page_Up:
            self.select(max(self.selected - 5, 0))
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and ctrl:
            self.activate(reveal=True)
        elif keyval == Gdk.KEY_y and ctrl:
            self.quicklook()
        else:
            return False
        return True

    def activate(self, reveal=False):
        r = self.current()
        if r:
            perform(self.shell, r, reveal)

    def quicklook(self):
        r = self.current()
        if r and r.path:
            close = getattr(self.shell, 'close_overlay', None)
            path = r.path
            if close:
                close()
            if not quicklook(self.shell, path):
                self.shell.open_file(path)

    # ---- preview pane
    def show_preview(self, r):
        ui.clear(self.preview)
        if not r:
            return
        self.preview.append(Gtk.Label(label=r.title, xalign=0, wrap=True, max_width_chars=34, css_classes=['title-label']))
        if r.path and os.path.exists(r.path):
            self._file_preview(r)
        else:
            if r.preview:
                self.preview.append(Gtk.Label(label=r.preview[:1500], xalign=0, yalign=0, wrap=True, max_width_chars=38, selectable=False, vexpand=True))
            elif r.subtitle:
                self.preview.append(Gtk.Label(label=r.subtitle, xalign=0, wrap=True, css_classes=['subtitle']))

    def _file_preview(self, r):
        path = Path(r.path)
        try:
            st = path.stat()
        except OSError:
            return
        ctype = Gio.content_type_guess(path.name, None)[0] or ''
        info = f"{ctype}\n{path.parent}\n{_human(st.st_size)} • {_when(st.st_mtime)}"
        self.preview.append(Gtk.Label(label=info, xalign=0, wrap=True, max_width_chars=38, css_classes=['subtitle']))
        if ctype in IMAGE_TYPES and st.st_size < 40_000_000 and not indexmod.is_excluded(path):
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
            pic.set_size_request(280, 200)
            self.preview.append(pic)

            def load():
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 280, 200, True)

            def done(pix):
                if pix and self.current() is r:
                    pic.set_paintable(Gdk.Texture.new_for_pixbuf(pix))
            self._async(lambda: load(), done)
        elif (path.suffix.lower() in indexmod.TEXT_EXT or ctype.startswith('text/')) and st.st_size < 1_000_000 and not indexmod.is_excluded(path):
            try:
                text = path.read_text(encoding='utf-8', errors='replace')[:1200]
            except OSError:
                text = ''
            self.preview.append(Gtk.Label(label=text, xalign=0, yalign=0, wrap=True, max_width_chars=38, vexpand=True, css_classes=['subtitle']))
        elif r.preview:
            self.preview.append(Gtk.Label(label=r.preview, xalign=0, yalign=0, wrap=True, max_width_chars=38))
        self.preview.append(ui.button('Quick Look', self.quicklook))


def _human(n):
    from ..backends import storage
    return storage.human(n)


def _when(ts):
    import time
    return time.strftime('%d %b %Y %H:%M', time.localtime(ts))


def open_seek(shell, applications_only=False, initial=''):
    return SeekPanel(shell, applications_only, initial)


def install_bar_field(shell, row):
    """A compact search field for the menu bar: typing opens the full panel with the text carried over."""
    entry = Gtk.SearchEntry(placeholder_text='Seek', width_chars=11, max_width_chars=16)
    entry.add_css_class('seek-bar-field')
    state = {'busy': False}

    def changed(e):
        text = e.get_text()
        if text and not state['busy']:
            state['busy'] = True
            e.set_text('')
            state['busy'] = False
            open_seek(shell, False, text)
    entry.connect('search-changed', changed)
    row.append(entry)
    return entry
