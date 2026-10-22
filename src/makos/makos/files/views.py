"""The four Files views: icons (grid), list (sortable, expandable), columns (unlimited stack) and cover.

Views never touch the disk themselves. The host (a browser Tab) supplies:
  activate(item)  selection_changed()  context_menu(item, widget, x, y)  drop(locations, target_item, ctrl)
  drag_locations(item) -> list   sort_changed(key, reverse)   load_children(item)   list_async(path, cb)
  rename_commit(item, text)      state: icon_size, sort_key, sort_reverse, virtual
"""
import os
import weakref

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from . import dnd, model, panes, widgets
from .widgets import Item, NameCell

MAX_TREE_DEPTH = 24


def item_at(widget, x, y):
    """Item under a point of ``widget`` (cell widgets carry .makos_item), else None."""
    w = widget.pick(x, y, Gtk.PickFlags.DEFAULT)
    while w is not None and w is not widget:
        item = getattr(w, 'makos_item', None)
        if item is not None:
            return item, w
        w = w.get_parent()
    return None, None


class BaseView:
    mode = ''

    def __init__(self, host):
        self.host = host
        self.bound = weakref.WeakValueDictionary()   # id(item) -> NameCell
        self.widget = None
        self._drop_cell = None

    # -- interface
    def selected_items(self):
        return []

    def select_items(self, items):
        pass

    def select_all(self):
        pass

    def focus(self):
        pass

    def set_icon_size(self, size):
        pass

    def rename(self, item):
        cell = self.bound.get(id(item))
        if cell is None:
            return False
        return cell.start_rename(lambda text, item=item: self.host.rename_commit(item, text))

    def step(self, delta):
        pass

    def refresh_cell(self, item):
        cell = self.bound.get(id(item))
        if cell is not None and cell.item is item:
            cell.bind(item)

    def teardown(self):
        pass

    # -- shared gestures
    def _wire(self, widget):
        """Context menu, blank-click deselect, drag source/target on the main scrolling widget."""
        menu = Gtk.GestureClick(button=3)
        menu.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def pressed(g, n, x, y):
            item, cell = item_at(widget, x, y)
            self.host.context_menu(item, widget, x, y)
            g.set_state(Gtk.EventSequenceState.CLAIMED)
        menu.connect('pressed', pressed)
        widget.add_controller(menu)
        left = Gtk.GestureClick(button=1)

        def left_pressed(g, n, x, y):
            item, _cell = item_at(widget, x, y)
            if item is None and n == 1:
                self.host.blank_click()
        left.connect('pressed', left_pressed)
        widget.add_controller(left)
        dnd.attach_target(widget, self._motion(widget), self._drop(widget), self._leave)

    def _folder_target(self, item):
        if item is not None and item.entry.is_dir and not item.cut:
            return item
        return None

    def _motion(self, widget):
        def motion(x, y):
            item, cell = item_at(widget, x, y)
            tgt = self._folder_target(item)
            self._leave()
            if tgt is not None and cell is not None:
                row = cell
                row.add_css_class('drop-target')
                self._drop_cell = weakref.ref(row)
            return self.host.can_drop(tgt)
        return motion

    def _leave(self):
        if self._drop_cell is not None:
            cell = self._drop_cell()
            if cell is not None:
                cell.remove_css_class('drop-target')
            self._drop_cell = None

    def _drop(self, widget):
        def drop(locations, x, y, ctrl):
            item, _cell = item_at(widget, x, y)
            self._leave()
            return self.host.drop(locations, self._folder_target(item), ctrl)
        return drop

    def _drag_source(self, cell):
        def locs(_x, _y):
            return self.host.drag_locations(cell.item) if cell.item is not None else []

        def icon():
            return widgets.icon_paintable(cell.item.entry.icon, 48) if cell.item is not None else None
        dnd.attach_source(cell, locs, icon)


# ================================================================ icon view

class IconView(BaseView):
    mode = 'icons'

    def __init__(self, host, store):
        super().__init__(host)
        self.store = store
        self.sel = Gtk.MultiSelection.new(store)
        self.grid = Gtk.GridView(model=self.sel, enable_rubberband=True, max_columns=200, min_columns=1)
        self.grid.add_css_class('icon-grid')
        self._factory()
        self.sel.connect('selection-changed', lambda *_: self.host.selection_changed())
        self.grid.connect('activate', lambda g, pos: self.host.activate(self.sel.get_item(pos)))
        self.scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.scroller.set_child(self.grid)
        self.widget = self.scroller
        self._wire(self.grid)

    def _factory(self):
        f = Gtk.SignalListItemFactory()

        def setup(_f, li):
            cell = NameCell('v', self.host.icon_size)
            cell.add_css_class('icon-cell')
            self._drag_source(cell)
            li.set_child(cell)

        def bind(_f, li):
            cell = li.get_child()
            item = li.get_item()
            cell.bind(item, self.host.icon_size)
            self.bound[id(item)] = cell
            li.set_selectable(True)

        def unbind(_f, li):
            cell = li.get_child()
            if cell.item is not None:
                self.bound.pop(id(cell.item), None)
            cell.unbind()
        f.connect('setup', setup)
        f.connect('bind', bind)
        f.connect('unbind', unbind)
        self.grid.set_factory(f)

    def set_icon_size(self, size):
        self._factory()

    def selected_items(self):
        bits = self.sel.get_selection()
        return [self.sel.get_item(bits.get_nth(i)) for i in range(bits.get_size())]

    def select_items(self, items):
        want = {id(i) for i in items}
        bits = Gtk.Bitset.new_empty()
        first = None
        for pos in range(self.store.get_n_items()):
            if id(self.store.get_item(pos)) in want:
                bits.add(pos)
                first = pos if first is None else first
        self.sel.set_selection(bits, Gtk.Bitset.new_range(0, self.store.get_n_items()))
        if first is not None:
            self.grid.scroll_to(first, Gtk.ListScrollFlags.FOCUS, None)

    def select_all(self):
        self.sel.select_all()

    def step(self, delta):
        n = self.store.get_n_items()
        bits = self.sel.get_selection()
        cur = bits.get_nth(0) if bits.get_size() else -1
        new = max(0, min(n - 1, cur + delta if cur >= 0 else 0))
        if n:
            self.sel.set_selection(Gtk.Bitset.new_range(new, 1), Gtk.Bitset.new_range(0, n))
            self.grid.scroll_to(new, Gtk.ListScrollFlags.NONE, None)

    def focus(self):
        self.grid.grab_focus()

    def rename(self, item):
        if id(item) not in self.bound:
            for pos in range(self.store.get_n_items()):
                if self.store.get_item(pos) is item:
                    self.grid.scroll_to(pos, Gtk.ListScrollFlags.NONE, None)
                    GLib.idle_add(lambda: (BaseView.rename(self, item), False)[1])
                    return True
        return BaseView.rename(self, item)


# ================================================================ list view

class ListView(BaseView):
    mode = 'list'
    COLUMNS = [('name', 'Name', True, 0), ('modified', 'Date Modified', False, 160), ('size', 'Size', False, 90),
               ('kind', 'Kind', False, 160), ('where', 'Where', False, 220)]

    def __init__(self, host, store):
        super().__init__(host)
        self.store = store
        self.tree = Gtk.TreeListModel.new(store, False, False, self._children)
        self.sel = Gtk.MultiSelection.new(self.tree)
        self.cv = Gtk.ColumnView(model=self.sel, show_column_separators=True, show_row_separators=False)
        self.cv.add_css_class('list-view')
        self.cv.set_enable_rubberband(True)
        self._muted = False
        self.cols = {}
        for key, title, expand, width in self.COLUMNS:
            col = Gtk.ColumnViewColumn(title=title, factory=self._column_factory(key))
            col.set_id(key)
            col.set_resizable(True)
            col.set_expand(expand)
            if width:
                col.set_fixed_width(width)
            col.set_sorter(Gtk.CustomSorter.new(lambda a, b, d=None: 0))
            if key == 'where':
                col.set_visible(bool(host.virtual))
            self.cv.append_column(col)
            self.cols[key] = col
        self.set_sort_indicator(host.sort_key, host.sort_reverse)
        self.cv.get_sorter().connect('changed', self._sorter_changed)
        self.sel.connect('selection-changed', lambda *_: self.host.selection_changed())
        self.cv.connect('activate', lambda v, pos: self.host.activate(self._item(self.tree.get_item(pos))))
        self.scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.scroller.set_child(self.cv)
        self.widget = self.scroller
        self._wire(self.cv)

    @staticmethod
    def _item(row):
        return row.get_item() if row is not None else None

    def _children(self, item):
        e = item.entry
        if not e.expandable or item.depth >= MAX_TREE_DEPTH or not e.path:
            return None
        if self.host.virtual:
            return None
        if item.children_store is None:
            item.children_store = Gio.ListStore.new(Item)
        return item.children_store

    def _column_factory(self, key):
        f = Gtk.SignalListItemFactory()

        def setup(_f, li):
            if key == 'name':
                exp = Gtk.TreeExpander()
                cell = NameCell('h', 20)
                exp.set_child(cell)
                exp.cell = cell
                exp._hid = None
                self._drag_source(cell)
                li.set_child(exp)
            else:
                lab = Gtk.Label(xalign=1 if key == 'size' else 0, ellipsize=Pango.EllipsizeMode.END)
                lab.add_css_class('cell-secondary')
                li.set_child(lab)

        def bind(_f, li):
            row = li.get_item()
            item = row.get_item()
            e = item.entry
            w = li.get_child()
            if key == 'name':
                w.set_list_row(row)
                w.cell.bind(item, 20)
                w.makos_item = item
                self.bound[id(item)] = w.cell
                if w._hid is not None:
                    try:
                        w._row.disconnect(w._hid)
                    except Exception:
                        pass
                w._row = row
                w._hid = row.connect('notify::expanded', lambda r, _p, it=item: self._expanded(r, it))
            else:
                w.makos_item = item
                if key == 'modified':
                    w.set_text(model.format_date(e.mtime if not e.deleted else e.deleted))
                elif key == 'size':
                    w.set_text('--' if e.is_dir else model.human_size(e.size))
                elif key == 'kind':
                    w.set_text(e.kind)
                elif key == 'where':
                    w.set_text(e.where)
                    w.set_tooltip_text(e.where)

        def unbind(_f, li):
            w = li.get_child()
            if key == 'name':
                if w._hid is not None:
                    try:
                        w._row.disconnect(w._hid)
                    except Exception:
                        pass
                    w._hid = None
                if w.cell.item is not None:
                    self.bound.pop(id(w.cell.item), None)
                w.cell.unbind()
                w.set_list_row(None)
            w.makos_item = None
        f.connect('setup', setup)
        f.connect('bind', bind)
        f.connect('unbind', unbind)
        return f

    def _expanded(self, row, item):
        if row.get_expanded() and not item.loaded:
            item.loaded = True
            self.host.load_children(item)

    def set_sort_indicator(self, key, reverse):
        self._muted = True
        try:
            col = self.cols.get(key)
            if col is not None:
                self.cv.sort_by_column(col, Gtk.SortType.DESCENDING if reverse else Gtk.SortType.ASCENDING)
        finally:
            self._muted = False

    def _sorter_changed(self, sorter, _change):
        if self._muted:
            return
        col = sorter.get_primary_sort_column()
        if col is None:
            return
        self.host.sort_changed(col.get_id(), sorter.get_primary_sort_order() == Gtk.SortType.DESCENDING)

    def show_where(self, visible):
        self.cols['where'].set_visible(visible)

    def selected_items(self):
        bits = self.sel.get_selection()
        return [self._item(self.tree.get_item(bits.get_nth(i))) for i in range(bits.get_size())]

    def select_items(self, items):
        want = {id(i) for i in items}
        bits = Gtk.Bitset.new_empty()
        first = None
        for pos in range(self.tree.get_n_items()):
            it = self._item(self.tree.get_item(pos))
            if id(it) in want:
                bits.add(pos)
                first = pos if first is None else first
        self.sel.set_selection(bits, Gtk.Bitset.new_range(0, max(self.tree.get_n_items(), 1)))
        if first is not None:
            self.cv.scroll_to(first, None, Gtk.ListScrollFlags.FOCUS, None)

    def select_all(self):
        self.sel.select_all()

    def step(self, delta):
        n = self.tree.get_n_items()
        bits = self.sel.get_selection()
        cur = bits.get_nth(0) if bits.get_size() else -1
        new = max(0, min(n - 1, cur + delta if cur >= 0 else 0))
        if n:
            self.sel.set_selection(Gtk.Bitset.new_range(new, 1), Gtk.Bitset.new_range(0, n))
            self.cv.scroll_to(new, None, Gtk.ListScrollFlags.NONE, None)

    def focus(self):
        self.cv.grab_focus()

    def rename(self, item):
        if id(item) not in self.bound:
            for pos in range(self.tree.get_n_items()):
                if self._item(self.tree.get_item(pos)) is item:
                    self.cv.scroll_to(pos, None, Gtk.ListScrollFlags.NONE, None)
                    GLib.idle_add(lambda: (BaseView.rename(self, item), False)[1])
                    return True
        return BaseView.rename(self, item)

    def expand_selected(self, expand):
        for pos in range(self.tree.get_n_items()):
            if self.sel.is_selected(pos):
                row = self.tree.get_row(pos)
                if row is not None and row.is_expandable():
                    row.set_expanded(expand)


# ================================================================ column view

COLUMN_WIDTH = 230


class MillerColumn:
    def __init__(self, view, path):
        self.view, self.path = view, path
        self.store = Gio.ListStore.new(Item)
        self.sel = Gtk.SingleSelection.new(self.store)
        self.sel.set_autoselect(False)
        self.sel.set_can_unselect(True)
        self.sel.set_selected(Gtk.INVALID_LIST_POSITION)
        self.list = Gtk.ListView(model=self.sel)
        self.list.add_css_class('miller-list')
        f = Gtk.SignalListItemFactory()

        def setup(_f, li):
            box = Gtk.Box(spacing=0)
            cell = NameCell('h', 20)
            cell.set_hexpand(True)
            arrow = Gtk.Label(label='›')
            arrow.add_css_class('miller-arrow')
            box.append(cell)
            box.append(arrow)
            box.cell, box.arrow = cell, arrow
            view._drag_source(cell)
            li.set_child(box)

        def bind(_f, li):
            box = li.get_child()
            item = li.get_item()
            box.cell.bind(item, 20)
            box.makos_item = item
            box.arrow.set_visible(item.entry.is_dir)
            view.bound[id(item)] = box.cell

        def unbind(_f, li):
            box = li.get_child()
            if box.cell.item is not None:
                view.bound.pop(id(box.cell.item), None)
            box.cell.unbind()
            box.makos_item = None
        f.connect('setup', setup)
        f.connect('bind', bind)
        f.connect('unbind', unbind)
        self.list.set_factory(f)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroller.set_size_request(COLUMN_WIDTH, -1)
        self.scroller.set_child(self.list)
        self.scroller.add_css_class('miller-column')
        self.sel.connect('selection-changed', lambda *_: view._column_selected(self))
        self.list.connect('activate', lambda l, pos: view.host.activate(self.store.get_item(pos)))
        view._wire_column(self)

    def selected(self):
        pos = self.sel.get_selected()
        return self.store.get_item(pos) if pos != Gtk.INVALID_LIST_POSITION else None


class ColumnsView(BaseView):
    mode = 'columns'

    def __init__(self, host, root_path):
        super().__init__(host)
        self.columns = []
        self.preview = None
        self._building = False
        self.box = Gtk.Box(spacing=0)
        self.box.add_css_class('miller')
        self.scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True, vscrollbar_policy=Gtk.PolicyType.EXTERNAL)
        self.scroller.set_child(self.box)
        self.widget = self.scroller
        self._want_end = 0
        self.scroller.get_hadjustment().connect('notify::upper', self._upper_changed)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._key)
        self.scroller.add_controller(keys)
        self.show_path(root_path)

    def _wire_column(self, col):
        widget = col.list
        menu = Gtk.GestureClick(button=3)
        menu.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def pressed(g, n, x, y):
            item, _c = item_at(widget, x, y)
            if item is not None and col.selected() is not item:
                for pos in range(col.store.get_n_items()):
                    if col.store.get_item(pos) is item:
                        col.sel.set_selected(pos)
            self.host.context_menu(item, widget, x, y, folder=col.path)
            g.set_state(Gtk.EventSequenceState.CLAIMED)
        menu.connect('pressed', pressed)
        widget.add_controller(menu)
        dnd.attach_target(widget, self._motion(widget), self._col_drop(widget, col), self._leave)

    def _col_drop(self, widget, col):
        def drop(locations, x, y, ctrl):
            item, _c = item_at(widget, x, y)
            self._leave()
            tgt = self._folder_target(item)
            return self.host.drop(locations, tgt, ctrl, folder=col.path)
        return drop

    # -- building
    def clear_from(self, index):
        while len(self.columns) > index:
            col = self.columns.pop()
            self.box.remove(col.scroller)
        if self.preview is not None:
            self.box.remove(self.preview)
            self.preview = None

    def add_column(self, path, select_name=None, then=None):
        col = MillerColumn(self, path)
        self.columns.append(col)
        self.box.append(col.scroller)

        def loaded(items, error):
            if col not in self.columns:
                return
            col.store.splice(0, 0, items)
            if error:
                self.host.show_error(error)
            if select_name:
                for pos, it in enumerate(items):
                    if it.entry.name == select_name:
                        self._building = True
                        col.sel.set_selected(pos)
                        self._building = False
                        col.list.scroll_to(pos, Gtk.ListScrollFlags.NONE, None)
                        break
            if then:
                then()
        self.host.list_async(path, loaded)
        GLib.idle_add(self._scroll_end)
        return col

    def _scroll_end(self):
        """Keep the newest column visible: scroll now and again whenever the stack grows for a moment."""
        self._want_end = GLib.get_monotonic_time() + 600000
        adj = self.scroller.get_hadjustment()
        adj.set_value(adj.get_upper())
        return False

    def _upper_changed(self, adj, _p):
        if GLib.get_monotonic_time() < self._want_end:
            adj.set_value(adj.get_upper() - adj.get_page_size())

    def show_path(self, path):
        """Rebuild the stack from the highest sensible ancestor down to ``path``."""
        path = os.path.abspath(path)
        home = os.path.expanduser('~')
        base = home if (path == home or path.startswith(home + os.sep)) else '/'
        parts = [] if path == base else os.path.relpath(path, base).split(os.sep)
        self.clear_from(0)
        chain = [base]
        for part in parts:
            chain.append(os.path.join(chain[-1], part))
        for i, folder in enumerate(chain):
            nxt = parts[i] if i < len(parts) else None
            self.add_column(folder, select_name=nxt)
        # the final column is the current folder: nothing selected in it yet

    def _column_selected(self, col):
        if self._building:
            return
        idx = self.columns.index(col) if col in self.columns else -1
        if idx < 0:
            return
        item = col.selected()
        self.clear_from(idx + 1)
        if item is not None:
            e = item.entry
            if e.is_dir and e.path:
                self._building = True
                self.add_column(e.path)
                self._building = False
                self.host.columns_navigated(e.path, item)
            else:
                self.preview = panes.PreviewPane(size=230)
                self.preview.set_size_request(COLUMN_WIDTH + 30, -1)
                self.preview.add_css_class('miller-preview')
                self.box.append(self.preview)
                self.preview.show(e)
                GLib.idle_add(self._scroll_end)
                self.host.columns_navigated(col.path, item)
        else:
            self.host.columns_navigated(col.path, None)
        self.host.selection_changed()

    def current_column(self):
        for col in reversed(self.columns):
            if col.selected() is not None:
                return col
        return self.columns[-1] if self.columns else None

    def selected_items(self):
        col = self.current_column()
        item = col.selected() if col else None
        return [item] if item is not None else []

    def folder_path(self):
        """The folder shown by the last folder column (the column list that has no selection or a file selected)."""
        col = self.columns[-1]
        sel = col.selected()
        if len(self.columns) >= 2 and sel is None:
            return col.path
        return col.path

    def select_items(self, items):
        col = self.columns[-1] if self.columns else None
        if col is None:
            return
        for it in items:
            for pos in range(col.store.get_n_items()):
                if col.store.get_item(pos).entry.path == it.entry.path:
                    col.sel.set_selected(pos)
                    return

    def select_all(self):
        pass

    def step(self, delta):
        col = self.current_column()
        if col is None:
            return
        pos = col.sel.get_selected()
        n = col.store.get_n_items()
        if n:
            col.sel.set_selected(max(0, min(n - 1, (0 if pos == Gtk.INVALID_LIST_POSITION else pos + delta))))

    def focus(self):
        col = self.current_column()
        if col:
            col.list.grab_focus()

    def rename(self, item):
        return BaseView.rename(self, item)

    def _key(self, _c, key, _code, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
            return False
        col = self.current_column()
        if col is None:
            return False
        idx = self.columns.index(col)
        if key == Gdk.KEY_Right:
            item = col.selected()
            if item is not None and item.entry.is_dir and idx + 1 < len(self.columns):
                nxt = self.columns[idx + 1]
                if nxt.store.get_n_items():
                    nxt.sel.set_selected(0)
                    nxt.list.grab_focus()
            elif item is None and col.store.get_n_items():
                col.sel.set_selected(0)
            return True
        if key == Gdk.KEY_Left:
            if idx > 0:
                self.columns[idx - 1].list.grab_focus()
                self.clear_from(idx)
                self.columns[idx - 1].list.grab_focus()
                self.host.selection_changed()
            return True
        return False


# ================================================================ cover view

class CoverView(BaseView):
    mode = 'cover'

    def __init__(self, host, store):
        super().__init__(host)
        self.store = store
        self.sel = Gtk.SingleSelection.new(store)
        self.sel.set_autoselect(True)
        self.sel.set_can_unselect(False)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.add_css_class('cover')
        self.stage = panes.PreviewPane(size=360, snippet=True)
        self.stage.set_vexpand(True)
        self.stage.set_valign(Gtk.Align.CENTER)
        self.stage.picture.set_size_request(520, 300)
        stage_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        stage_scroll.set_child(self.stage)
        outer.append(stage_scroll)
        self.strip = Gtk.ListView(model=self.sel, orientation=Gtk.Orientation.HORIZONTAL)
        self.strip.add_css_class('cover-strip')
        f = Gtk.SignalListItemFactory()

        def setup(_f, li):
            cell = NameCell('v', 72)
            cell.add_css_class('cover-cell')
            cell.set_size_request(104, -1)
            self._drag_source(cell)
            li.set_child(cell)

        def bind(_f, li):
            cell = li.get_child()
            item = li.get_item()
            cell.bind(item, 72)
            self.bound[id(item)] = cell

        def unbind(_f, li):
            cell = li.get_child()
            if cell.item is not None:
                self.bound.pop(id(cell.item), None)
            cell.unbind()
        f.connect('setup', setup)
        f.connect('bind', bind)
        f.connect('unbind', unbind)
        self.strip.set_factory(f)
        sc = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True)
        sc.set_child(self.strip)
        sc.set_min_content_height(132)
        outer.append(sc)
        self.widget = outer
        self.sel.connect('notify::selected-item', self._changed)
        self.strip.connect('activate', lambda l, pos: self.host.activate(self.store.get_item(pos)))
        self._wire(self.strip)
        key = Gtk.EventControllerKey()
        self.strip.add_controller(key)

    def _changed(self, *_):
        item = self.sel.get_selected_item()
        if item is not None:
            self.stage.show(item.entry)
            pos = self.sel.get_selected()
            self.strip.scroll_to(pos, Gtk.ListScrollFlags.NONE, None)
        else:
            self.stage.clear()
        self.host.selection_changed()

    def selected_items(self):
        item = self.sel.get_selected_item()
        return [item] if item is not None else []

    def select_items(self, items):
        for it in items:
            for pos in range(self.store.get_n_items()):
                if self.store.get_item(pos) is it:
                    self.sel.set_selected(pos)
                    return

    def step(self, delta):
        pos = self.sel.get_selected()
        n = self.store.get_n_items()
        if n:
            self.sel.set_selected(max(0, min(n - 1, pos + delta)))

    def select_all(self):
        pass

    def focus(self):
        self.strip.grab_focus()
