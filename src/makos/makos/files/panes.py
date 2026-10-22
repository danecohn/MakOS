"""PreviewPane: thumbnail + metadata + text snippet, used by column view, cover view and Get Info."""
import threading

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, GdkPixbuf, Gtk, Pango

from . import content, model, widgets


def texture_from_bytes(data):
    try:
        return Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
    except GLib.Error:
        return None


class PreviewPane(Gtk.Box):
    """Shows one file: best-effort fast picture, a few metadata rows and optional text snippet."""

    def __init__(self, size=260, snippet=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.size, self.want_snippet = size, snippet
        self.gen = 0
        self.add_css_class('preview-pane')
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        self.picture.set_size_request(size, int(size * .8))
        self.icon = Gtk.Image()
        self.stack = Gtk.Stack(hexpand=True)
        self.stack.add_named(self.icon, 'icon')
        self.stack.add_named(self.picture, 'picture')
        self.append(self.stack)
        self.title = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=26, justify=Gtk.Justification.CENTER)
        self.title.add_css_class('preview-title')
        self.append(self.title)
        self.grid = Gtk.Grid(column_spacing=10, row_spacing=3, halign=Gtk.Align.CENTER)
        self.append(self.grid)
        self.text = Gtk.Label(xalign=0, yalign=0, wrap=True, wrap_mode=Pango.WrapMode.CHAR, selectable=False,
                              max_width_chars=34, lines=9, ellipsize=Pango.EllipsizeMode.END)
        self.text.add_css_class('preview-snippet')
        self.text.set_visible(False)
        self.append(self.text)

    def clear(self):
        self.gen += 1
        self.title.set_text('')
        self._rows([])
        self.text.set_visible(False)

    def _rows(self, rows):
        child = self.grid.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt
        for i, (k, v) in enumerate(rows):
            if k == 'Name':
                continue
            a = Gtk.Label(label=k, xalign=1, yalign=0, css_classes=['subtitle'])
            b = Gtk.Label(label=str(v), xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=26, selectable=True)
            self.grid.attach(a, 0, i, 1, 1)
            self.grid.attach(b, 1, i, 1, 1)

    def show(self, entry):
        self.gen += 1
        gen = self.gen
        self.title.set_text(entry.name)
        widgets.set_icon(self.icon, entry.icon, int(self.size * .6))
        self.stack.set_visible_child_name('icon')
        self.text.set_visible(False)
        self._rows([('Kind', entry.kind), ('Size', model.human_size(entry.size) if not entry.is_dir else '--'),
                    ('Modified', model.format_date(entry.mtime))])
        if not entry.path:
            return
        path, size = entry.path, self.size

        def work():
            kind = content.classify(path)
            rows = content.metadata_rows(path, deep=True)
            image = None
            snippet = ''
            try:
                if kind == 'image' and entry.size < content.IMAGE_LIMIT:
                    pb = content.pixbuf_thumbnail(path, size * 2)
                    image = Gdk.Texture.new_for_pixbuf(pb) if pb else None
                elif kind == 'pdf':
                    data = content.pdf_page_png(path, 1, size * 2)
                    image = texture_from_bytes(data) if data else None
                elif kind == 'office':
                    data = content.office_thumbnail(path, allow_soffice=False)
                    image = texture_from_bytes(data) if data else None
                elif kind == 'text' and self.want_snippet:
                    snippet = content.read_text(path, 1200)[0][:900]
            except Exception:
                pass
            GLib.idle_add(done, rows, image, snippet)

        def done(rows, image, snippet):
            if gen != self.gen:
                return False
            self._rows(rows)
            if image is not None:
                self.picture.set_paintable(image)
                self.stack.set_visible_child_name('picture')
            if snippet:
                self.text.set_text(snippet)
                self.text.set_visible(True)
            return False
        threading.Thread(target=work, daemon=True, name='makos-preview').start()
