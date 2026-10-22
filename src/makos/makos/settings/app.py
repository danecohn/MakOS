"""The Settings window: icon grid, search, and one page per pane (built lazily from pane_<id>.py)."""
import gi

gi.require_version('Gtk', '4.0')
import importlib
import traceback

from gi.repository import Gtk

from .. import common, ui
from . import registry
from .ctx import Ctx


class Settings:
    def __init__(self, app, start=None):
        self.app = app
        self.win = ui.window(app, 'Settings', 960, 820)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.status = Gtk.Label(label='', xalign=0, css_classes=['settings-status'], wrap=True)
        self.ctx = Ctx(app, self.win, self.status)
        self.current = None
        self.tiles = {}
        self.back = ui.button('Show All', self.show_all)
        self.back.set_sensitive(False)
        self.win._bar.pack_start(self.back)
        self.search = Gtk.SearchEntry(placeholder_text='Search settings', width_chars=22)
        self.search.connect('search-changed', self._filter)
        self.search.connect('activate', self._first_match)
        self.win._bar.pack_end(self.search)
        self.all = ui.box(True, 0)
        self._build_grid()
        self.stack.add_named(ui.scroll(self.all), 'all')
        outer = ui.box(True, 0)
        outer.append(self.stack)
        outer.append(self.status)
        self.win.set_child(outer)
        self.win.present()
        if start:
            self.pane(start)

    # ---- grid
    def _build_grid(self):
        self.sections = []
        for title, panes in registry.GROUPS:
            section = ui.box(True, 4, 'settings-section')
            section.append(Gtk.Label(label=title, xalign=0, css_classes=['section-title']))
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, min_children_per_line=3,
                               column_spacing=3, row_spacing=3, homogeneous=True)
            for p in panes:
                tile = ui.box(True, 7)
                tile.append(ui.icon(p.icon, 48))
                tile.append(Gtk.Label(label=p.title, wrap=True, max_width_chars=17, justify=Gtk.Justification.CENTER))
                b = ui.button('', lambda pid=p.id: self.pane(pid), 'settings-tile')
                b.set_child(tile)
                b.set_size_request(116, 95)
                b.set_tooltip_text(p.title)
                flow.append(b)
                self.tiles[p.id] = b.get_parent()
            section.append(flow)
            self.sections.append((section, flow, panes))
            self.all.append(section)

    def _filter(self, entry):
        words = entry.get_text().lower().split()
        matching = {p.id for p in registry.search(entry.get_text())} if words else None
        for section, _flow, panes in self.sections:
            visible = False
            for p in panes:
                show = matching is None or p.id in matching
                self.tiles[p.id].set_visible(show)
                visible = visible or show
            section.set_visible(visible)
        if self.current:
            self.show_all()

    def _first_match(self, entry):
        found = registry.search(entry.get_text())
        if found:
            self.pane(found[0].id)

    # ---- navigation
    def show_all(self):
        self.stack.set_visible_child_name('all')
        self.back.set_sensitive(False)
        self.current = None
        self.ctx.flash('')

    def pane(self, name):
        """Show a pane by id or title (the shell opens panes by title, e.g. 'Bluetooth')."""
        info = registry.find(name)
        if not info:
            self.show_all()
            return
        old = self.stack.get_child_by_name('pane')
        if old:
            self.stack.remove(old)
        col = ui.box(True, 16, 'sheet')
        col.append(Gtk.Label(label=info.title, xalign=0, css_classes=['hero']))
        try:
            module = importlib.import_module(f'{__package__}.{info.module}')
            module.build(col, self.ctx)
        except Exception as error:  # noqa: BLE001 - a broken pane must never take the whole app down
            traceback.print_exc()
            col.append(Gtk.Label(label='This pane could not be loaded: ' + str(error)[:200], xalign=0, wrap=True))
        self.stack.add_named(ui.scroll(col), 'pane')
        self.stack.set_visible_child_name('pane')
        self.back.set_sensitive(True)
        self.current = info.id
