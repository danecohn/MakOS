"""Shared GTK pieces: list items, icons, thumbnails, name cells with inline rename, popup menus."""
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from .. import common
from . import content, model, tags


class Item(GObject.Object):
    """One row/cell of a folder listing. ``entry`` is a model.Entry."""
    __gtype_name__ = 'MakosFilesItem'

    def __init__(self, entry, depth=0, ancestors=frozenset()):
        super().__init__()
        self.entry = entry
        self.depth = depth
        self.ancestors = ancestors
        self.children_store = None
        self.loaded = False
        self.cut = False

    @property
    def name(self):
        return self.entry.name


# ---------------------------------------------------------------- icons

_TEXTURES = {}
_FALLBACKS = {'file-font': 'file-generic', 'file-executable': 'file-generic', 'file-disk-image': 'file-archive',
              'folder-home': 'folder', 'folder-recent': 'folder', 'folder-tag': 'folder', 'network-server': 'drive-network',
              'file-database': 'file-generic'}


def _theme():
    return Gtk.IconTheme.get_for_display(Gdk.Display.get_default())


def icon_paintable(name, size=48):
    """Paintable for a MakkOS icon name (app PNG art when present, otherwise the vector icon)."""
    key = name
    hit = _TEXTURES.get(key)
    if hit is not None:
        return hit
    png = common.SHARE / 'icons/MakkOS/128x128/apps' / (name + '.png')
    paint = None
    if png.exists():
        try:
            paint = Gdk.Texture.new_from_filename(str(png))
        except GLib.Error:
            paint = None
    if paint is None:
        theme = _theme()
        for candidate in (name, _FALLBACKS.get(name), 'file-generic'):
            if candidate and theme.has_icon('makos-' + candidate):
                paint = theme.lookup_icon('makos-' + candidate, None, 128, 1, Gtk.TextDirection.NONE, 0)
                break
    if paint is not None:
        _TEXTURES[key] = paint
    return paint


def make_icon(name, size=48):
    img = Gtk.Image()
    set_icon(img, name, size)
    return img


def set_icon(img, name, size):
    img.set_from_paintable(icon_paintable(name, size))
    img.set_pixel_size(size)


# ---------------------------------------------------------------- thumbnails

class Token:
    cancelled = False


class Thumbs:
    """Background thumbnail decoding. Textures are created on the main thread."""

    def __init__(self, workers=3, capacity=600):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='makos-thumb')
        self.cache = OrderedDict()
        self.capacity = capacity
        self.failed = set()

    def key(self, entry, size):
        return (entry.path, entry.mtime, entry.size, size)

    def wanted(self, entry):
        if entry.is_dir or not entry.path or not entry.mime.startswith('image/'):
            return False
        return entry.size < (4_000_000 if 'svg' in entry.mime else content.IMAGE_LIMIT)

    def request(self, entry, size, callback):
        token = Token()
        if not self.wanted(entry):
            return token
        key = self.key(entry, size)
        tex = self.cache.get(key)
        if tex is not None:
            self.cache.move_to_end(key)
            callback(tex)
            return token
        if key in self.failed:
            return token

        def work():
            pb = content.pixbuf_thumbnail(entry.path, size)
            if token.cancelled and pb is None:
                return
            GLib.idle_add(done, pb)

        def done(pb):
            if pb is None:
                self.failed.add(key)
                return False
            try:
                tex = Gdk.Texture.new_for_pixbuf(pb)
            except Exception:
                self.failed.add(key)
                return False
            self.cache[key] = tex
            while len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
            if not token.cancelled:
                callback(tex)
            return False
        self.pool.submit(work)
        return token


THUMBS = Thumbs()


# ---------------------------------------------------------------- name cell

class NameCell(Gtk.Box):
    """Icon + label (+ tag dots) with an in-place rename entry. layout 'v' (icon view) or 'h' (list/columns)."""

    def __init__(self, layout='v', size=48):
        vertical = layout == 'v'
        super().__init__(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                         spacing=4 if vertical else 8)
        self.layout, self.size = layout, size
        self.item = None
        self._token = None
        self._rename_done = None
        self.add_css_class('name-cell')
        self.add_css_class('name-cell-v' if vertical else 'name-cell-h')
        self.overlay = Gtk.Overlay()
        self.icon = Gtk.Image()
        self.overlay.set_child(self.icon)
        self.badge = Gtk.Image(halign=Gtk.Align.START, valign=Gtk.Align.END)
        self.dots = Gtk.Box(spacing=0, halign=Gtk.Align.END, valign=Gtk.Align.END)
        self.dots.add_css_class('tag-dots')
        self.overlay.add_overlay(self.dots)
        self.append(self.overlay)
        self.label = Gtk.Label(xalign=0.5 if vertical else 0, hexpand=not vertical, ellipsize=Pango.EllipsizeMode.MIDDLE if vertical else Pango.EllipsizeMode.END)
        if vertical:
            self.label.set_wrap(True)
            self.label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.label.set_lines(2)
            self.label.set_justify(Gtk.Justification.CENTER)
            self.label.set_max_width_chars(14)
            self.label.add_css_class('icon-label')
        self.entry = Gtk.Entry(hexpand=True)
        self.entry.add_css_class('rename-entry')
        self.stack = Gtk.Stack(hexpand=not vertical)
        self.stack.add_named(self.label, 'label')
        self.stack.add_named(self.entry, 'entry')
        self.append(self.stack)
        self.entry.connect('activate', self._commit)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key)
        self.entry.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect('leave', self._leave)
        self.entry.add_controller(focus)

    def set_size(self, size):
        self.size = size

    def bind(self, item, size=None, with_tags=True):
        self.item = item
        self.makos_item = item
        if size:
            self.size = size
        e = item.entry
        self.cancel_rename()
        self.label.set_text(e.name)
        set_icon(self.icon, e.icon, self.size)
        self.icon.set_opacity(.55 if (e.hidden or item.cut) else 1.0)
        self.label.set_opacity(.6 if (e.hidden or item.cut) else 1.0)
        self.set_tooltip_text(e.name if e.path == '' else f'{e.name}\n{e.kind}')
        if self._token:
            self._token.cancelled = True
        self._token = THUMBS.request(e, max(self.size * 2, 96) if self.layout == 'v' else 64, self._thumb)
        self._set_dots(item, with_tags)
        if e.is_symlink:
            self.add_css_class('is-alias')
        else:
            self.remove_css_class('is-alias')
        if self.layout == 'v':
            self.set_size_request(self.size + 36, -1)

    def _thumb(self, tex):
        if self.item is not None:
            self.icon.set_from_paintable(tex)
            self.icon.set_pixel_size(self.size)

    def _set_dots(self, item, with_tags):
        child = self.dots.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.dots.remove(child)
            child = nxt
        if not with_tags or not item.entry.path:
            return
        names = tags.STORE.get_tags(item.entry.path) if not item.entry.path.startswith('trash') else []
        item.tag_names = names
        for t in names[:4]:
            dot = Gtk.Label(label='●')
            dot.add_css_class('tagdot')
            dot.add_css_class('tagdot-' + (t.casefold() if t.title() in tags.COLOURS else 'custom'))
            dot.set_tooltip_text(t)
            self.dots.append(dot)

    def unbind(self):
        if self._token:
            self._token.cancelled = True
        self.cancel_rename()
        self.item = None
        self.makos_item = None

    # -- inline rename
    def start_rename(self, on_done):
        if self.item is None:
            return False
        self._rename_done = on_done
        name = self.item.entry.name
        self.entry.set_text(name)
        self.stack.set_visible_child_name('entry')
        self.entry.grab_focus()
        stem = model.split_name(name)[0] if not self.item.entry.is_dir else name
        self.entry.select_region(0, len(stem))
        return True

    def cancel_rename(self):
        self._rename_done = None
        if self.stack.get_visible_child_name() != 'label':
            self.stack.set_visible_child_name('label')

    def _commit(self, *_):
        done, self._rename_done = self._rename_done, None
        text = self.entry.get_text()
        self.stack.set_visible_child_name('label')
        if done:
            done(text)

    def _key(self, _c, key, _code, _state):
        if key == Gdk.KEY_Escape:
            self.cancel_rename()
            return True
        return False

    def _leave(self, *_):
        if self._rename_done is not None and self.stack.get_visible_child_name() == 'entry':
            GLib.idle_add(self._commit_if_still)

    def _commit_if_still(self):
        if self._rename_done is not None and not self.entry.has_focus() and self.stack.get_visible_child_name() == 'entry':
            self._commit()
        return False


# ---------------------------------------------------------------- popup menus

def popup_menu(parent, x, y, rows):
    """Show a flat popover menu. rows: ('Label', callback[, enabled]) | None (separator) | ('title', 'Text')
    | ('widget', Gtk.Widget) | ('submenu', 'Label', [rows])."""
    pop = Gtk.Popover()
    pop.add_css_class('files-menu')
    pop.set_parent(parent)
    pop.set_has_arrow(False)
    pop.set_halign(Gtk.Align.START)
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    pop.set_pointing_to(rect)
    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    _fill_menu(col, rows, pop)
    pop.set_child(col)
    pop.connect('closed', lambda p: GLib.idle_add(p.unparent))
    pop.popup()
    return pop


def _fill_menu(col, rows, pop):
    for row in rows:
        if row is None:
            col.append(Gtk.Separator(margin_top=3, margin_bottom=3))
        elif row[0] == 'title':
            col.append(Gtk.Label(label=row[1], xalign=0, css_classes=['source-heading']))
        elif row[0] == 'widget':
            col.append(row[1])
        elif row[0] == 'submenu':
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            _fill_menu(inner, row[2], pop)
            sub = Gtk.MenuButton(label=row[1] + '  ›', has_frame=False, direction=Gtk.ArrowType.RIGHT)
            sub.add_css_class('menu-item')
            sub.get_first_child().set_halign(Gtk.Align.START) if sub.get_first_child() else None
            p2 = Gtk.Popover()
            p2.set_child(inner)
            sub.set_popover(p2)
            col.append(sub)
        else:
            label, cb = row[0], row[1]
            enabled = row[2] if len(row) > 2 else True
            b = Gtk.Button(label=label, halign=Gtk.Align.FILL, sensitive=bool(enabled))
            b.add_css_class('menu-item')
            child = b.get_child()
            if isinstance(child, Gtk.Label):
                child.set_xalign(0)
            b.connect('clicked', lambda _b, cb=cb: (pop.popdown(), GLib.idle_add(lambda: (cb(), False)[1])))
            col.append(b)


def human_count(n, singular, plural=None):
    return f'{n} {singular if n == 1 else (plural or singular + "s")}'
