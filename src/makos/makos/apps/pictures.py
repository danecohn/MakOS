"""Pictures: a viewer over ~/Pictures with albums by folder and date, slideshow and non-destructive edits.

Originals are never modified. Edits (rotate, crop, brightness) are stored as small JSON sidecars in the
user's data folder and applied on display; "Save Edited Copy" writes a new file under Pictures/Edited.
"""
import datetime as dt
import hashlib
import io
import json
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
from .. import ui
from .base import AppWindow, data_dir, cache_dir, atomic_write
from .preview import pil_to_cairo

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff'}
MAX_ITEMS = 20000
THUMB = 200


@dataclass
class Item:
    path: Path
    folder: str
    taken: float


def exif_date(path):
    """Capture time from EXIF if present, else None. Never raises."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            raw = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        if raw:
            return dt.datetime.strptime(str(raw)[:19], '%Y:%m:%d %H:%M:%S').timestamp()
    except Exception:  # corrupt files are simply listed by modification time
        pass
    return None


def scan(root, limit=MAX_ITEMS, use_exif=True):
    """Pictures under root: skips hidden folders and symlinked directories; newest first."""
    root = Path(root)
    items = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not os.path.islink(os.path.join(base, d)))
        for name in sorted(files):
            p = Path(base) / name
            if name.startswith('.') or p.suffix.lower() not in EXTENSIONS or p.is_symlink():
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            rel = str(Path(base).relative_to(root))
            items.append(Item(p, '' if rel == '.' else rel, (exif_date(p) if use_exif else None) or m))
            if len(items) >= limit:
                return sorted(items, key=lambda i: -i.taken)
    return sorted(items, key=lambda i: -i.taken)


def albums_by_folder(items):
    out = {}
    for i in items:
        out.setdefault(i.folder or 'Pictures', []).append(i)
    return dict(sorted(out.items(), key=lambda kv: kv[0].casefold()))


def albums_by_date(items):
    out = {}
    for i in items:
        out.setdefault(dt.datetime.fromtimestamp(i.taken).strftime('%Y-%m'), []).append(i)
    return {dt.datetime.strptime(k, '%Y-%m').strftime('%B %Y'): v for k, v in sorted(out.items(), reverse=True)}


# ------------------------------------------------------------------ edits
DEFAULT_EDITS = {'rotate': 0, 'brightness': 0, 'crop': None}


def edits_path(photo, root=None):
    base = Path(root) if root else data_dir('pictures', 'edits')
    return base / (hashlib.sha256(str(Path(photo).resolve()).encode()).hexdigest()[:32] + '.json')


def clean_edits(raw):
    e = dict(DEFAULT_EDITS)
    if isinstance(raw, dict):
        if raw.get('rotate') in (0, 90, 180, 270):
            e['rotate'] = raw['rotate']
        if isinstance(raw.get('brightness'), (int, float)):
            e['brightness'] = max(-100, min(100, int(raw['brightness'])))
        c = raw.get('crop')
        if isinstance(c, list) and len(c) == 4 and all(isinstance(v, (int, float)) for v in c):
            l, t, r, b = (min(1, max(0, float(v))) for v in c)
            if r - l > .01 and b - t > .01:
                e['crop'] = [l, t, r, b]
    return e


def load_edits(photo, root=None):
    try:
        return clean_edits(json.loads(edits_path(photo, root).read_text()))
    except (OSError, ValueError):
        return dict(DEFAULT_EDITS)


def save_edits(photo, edits, root=None):
    p = edits_path(photo, root)
    if clean_edits(edits) == DEFAULT_EDITS:
        if p.exists():
            p.rename(p.with_suffix('.bak'))  # reverting everything keeps a recoverable copy rather than deleting
        return
    atomic_write(p, json.dumps(clean_edits(edits)), 0o600)


def apply_edits(image, edits):
    """Rotate (clockwise), then crop (normalised to the rotated image), then brightness."""
    from PIL import Image, ImageEnhance
    e = clean_edits(edits)
    img = image.convert('RGB')
    if e['rotate']:
        img = img.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}[e['rotate']])
    if e['crop']:
        w, h = img.size
        l, t, r, b = e['crop']
        img = img.crop((round(l * w), round(t * h), round(r * w), round(b * h)))
    if e['brightness']:
        img = ImageEnhance.Brightness(img).enhance(1 + e['brightness'] / 100)
    return img


def open_image(path, maximum=None):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 120_000_000
    with Image.open(path) as im:
        im.seek(0)
        im = ImageOps.exif_transpose(im).convert('RGB')
        if maximum:
            im.thumbnail((maximum, maximum))
        return im.copy()


def save_edited_copy(photo, edits, dest_dir):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(photo).stem
    target = dest_dir / f'{stem} edited.png'
    n = 2
    while target.exists():
        target = dest_dir / f'{stem} edited {n}.png'
        n += 1
    apply_edits(open_image(photo), edits).save(target, 'PNG')
    return target


def thumb_path(photo):
    st = Path(photo).stat()
    return cache_dir('pictures', 'thumbs') / (hashlib.sha256(f'{Path(photo).resolve()}:{st.st_mtime_ns}:{st.st_size}'.encode()).hexdigest()[:32] + '.png')


def make_thumb(photo, edits=None):
    out = thumb_path(photo)
    edited = edits and clean_edits(edits) != DEFAULT_EDITS
    if out.exists() and not edited:
        return out
    img = open_image(photo, THUMB * 2)
    if edited:
        img = apply_edits(img, edits)
    img.thumbnail((THUMB, THUMB))
    if edited:
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        return buf.getvalue()
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, 'PNG')
    return out


MENU = [('File', [('Save Edited Copy', 'save_copy', '<Primary>s'), ('Reload Library', 'reload', '<Primary>r'), None, ('Close', 'close', '<Primary>w')]),
        ('Edit', [('Rotate Left', 'rotate_left', '<Primary>l'), ('Rotate Right', 'rotate_right', '<Primary>r'), ('Crop to Square', 'crop_square', None), ('Revert to Original', 'revert', None)]),
        ('View', [('Library', 'show_grid', 'Escape'), ('Previous', 'prev', 'Left'), ('Next', 'next', 'Right'), ('Start Slideshow', 'slideshow', '<Primary><Shift>s')])]


class Pictures:
    def __init__(self, app, root=None, items=None):
        self.root = Path(root) if root else (Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or Path.home() / 'Pictures'))
        self.items, self.shown, self.index, self.edits, self.slide = [], [], 0, dict(DEFAULT_EDITS), 0
        self.crop_mode, self.crop_rect, self.thumbq = False, None, queue.Queue()
        self.aw = AppWindow(app, 'Pictures', 980, 680, MENU)
        self.win = self.aw.win
        for name, fn in (('save_copy', self.save_copy), ('reload', self.reload), ('close', self.win.close), ('rotate_left', lambda: self.rotate(-90)), ('rotate_right', lambda: self.rotate(90)),
                         ('crop_square', self.crop_square), ('revert', self.revert), ('show_grid', self.show_grid), ('prev', lambda: self.step(-1)), ('next', lambda: self.step(1)), ('slideshow', self.toggle_slideshow)):
            self.aw.action(name, fn)
        self.stack = Gtk.Stack(vexpand=True)
        self.albums = Gtk.ListBox(css_classes=['app-sidebar'])
        self.albums.connect('row-selected', self.pick_album)
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12, min_children_per_line=2, homogeneous=True, column_spacing=6, row_spacing=6, valign=Gtk.Align.START)
        paned = Gtk.Paned(position=190)
        paned.set_start_child(ui.scroll(self.albums))
        paned.set_end_child(ui.scroll(self.grid))
        paned.set_shrink_start_child(False)
        self.stack.add_named(paned, 'grid')
        self.stack.add_named(self.build_viewer(), 'viewer')
        self.aw.body.append(self.stack)
        threading.Thread(target=self.thumb_worker, daemon=True).start()
        if items is not None:
            self.set_items(items)
        else:
            self.reload()
        self.win.connect('close-request', lambda *_: (self.thumbq.put(None), self.stop_slideshow(), False)[2])

    # ---- library
    def reload(self):
        self.aw.say('Scanning ' + str(self.root) + '…')

        def work():
            items = scan(self.root) if self.root.exists() else []
            GLib.idle_add(lambda: (self.set_items(items), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def set_items(self, items):
        self.items = items
        ui.clear(self.albums)
        entries = [('Library', items, None)]
        folders, dates = albums_by_folder(items), albums_by_date(items)
        sections = [('Library', {'All Pictures': items}), ('Albums by folder', folders), ('Albums by date', dates)]
        first = None
        for title, group in sections:
            head = Gtk.ListBoxRow(selectable=False, activatable=False)
            head.set_child(Gtk.Label(label=title, xalign=0, css_classes=['source-heading']))
            self.albums.append(head)
            for name, list_ in group.items():
                row = Gtk.ListBoxRow()
                row.album = list_
                row.set_child(Gtk.Label(label=f'{name}  ({len(list_)})', xalign=0))
                self.albums.append(row)
                first = first or row
        if first:
            self.albums.select_row(first)
        else:
            self.fill_grid([])
        self.aw.say(f'{len(items)} pictures in {self.root}')

    def pick_album(self, _b, row):
        if row is not None and hasattr(row, 'album'):
            self.fill_grid(row.album)

    def fill_grid(self, items):
        self.shown = items
        child = self.grid.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt
        if not items:
            self.grid.append(Gtk.Label(label=f'No pictures yet. Put images in {self.root} and choose File → Reload Library.', css_classes=['hint'], margin_top=40))
            return
        for i, item in enumerate(items[:2000]):
            pic = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.COVER)
            pic.set_size_request(THUMB - 40, THUMB - 40)
            b = Gtk.Button(css_classes=['tile'])
            b.set_child(pic)
            b.set_tooltip_text(item.path.name)
            b.connect('clicked', lambda _b, k=i: self.open_item(k))
            self.grid.append(b)
            self.thumbq.put((pic, item.path))

    def thumb_worker(self):
        while True:
            job = self.thumbq.get()
            if job is None:
                return
            pic, path = job
            try:
                edits = load_edits(path)
                res = make_thumb(path, edits)
                data = res if isinstance(res, bytes) else Path(res).read_bytes()
            except (OSError, ValueError):
                continue
            GLib.idle_add(lambda pic=pic, data=data: (pic.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))), False)[1])

    # ---- viewer
    def build_viewer(self):
        col = ui.box(True)
        bar = ui.box(spacing=6, css='metal-toolbar')
        for label, fn in (('‹ Library', self.show_grid), ('‹', lambda: self.step(-1)), ('›', lambda: self.step(1)), ('↺', lambda: self.rotate(-90)), ('↻', lambda: self.rotate(90)),
                          ('Crop', self.toggle_crop), ('Revert', self.revert), ('Slideshow', self.toggle_slideshow), ('Save Edited Copy', self.save_copy)):
            bar.append(ui.button(label, fn))
        bar.append(Gtk.Label(label='Brightness'))
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -100, 100, 5)
        self.bright.set_size_request(160, -1)
        self.bright.connect('value-changed', self.on_bright)
        bar.append(self.bright)
        col.append(bar)
        self.canvas = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.canvas.set_draw_func(self.draw)
        drag = Gtk.GestureDrag()
        drag.connect('drag-begin', lambda _g, x, y: self.crop_mode and setattr(self, 'crop_start', (x, y)))
        drag.connect('drag-update', lambda _g, dx, dy: self.crop_update(dx, dy))
        drag.connect('drag-end', lambda _g, dx, dy: self.crop_update(dx, dy, final=True))
        self.canvas.add_controller(drag)
        col.append(self.canvas)
        self.surface = None
        return col

    def open_item(self, i):
        self.index = i
        self.load_current()
        self.stack.set_visible_child_name('viewer')

    def load_current(self):
        item = self.shown[self.index]
        self.edits = load_edits(item.path)
        self.crop_mode, self.crop_rect = False, None
        try:
            self.original = open_image(item.path, 3000)
        except (OSError, ValueError) as error:
            self.original, self.surface = None, None
            self.aw.say('Cannot open: ' + str(error))
            self.canvas.queue_draw()
            return
        self.bright.set_value(self.edits['brightness'])
        self.rerender()

    def rerender(self):
        if not self.original:
            return
        view = dict(self.edits)
        if self.crop_mode:
            view['crop'] = None
        self.surface = pil_to_cairo(apply_edits(self.original, view))
        self.canvas.queue_draw()
        item = self.shown[self.index]
        self.aw.say(f'{item.path.name}   {self.index + 1} of {len(self.shown)}' + ('   edited (original untouched)' if clean_edits(self.edits) != DEFAULT_EDITS else ''))

    def layout(self):
        w, h = self.canvas.get_width(), self.canvas.get_height()
        sw, sh = self.surface.get_width(), self.surface.get_height()
        scale = min((w - 20) / sw, (h - 20) / sh, 1.0 if not self.slide else 10)
        return scale, (w - sw * scale) / 2, (h - sh * scale) / 2

    def draw(self, _a, cr, w, h):
        cr.set_source_rgb(.1, .11, .13)
        cr.paint()
        if not self.surface:
            return
        scale, ox, oy = self.layout()
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        cr.set_source_surface(self.surface, 0, 0)
        cr.paint()
        if self.crop_mode and self.crop_rect:
            l, t, r, b = self.crop_rect
            sw, sh = self.surface.get_width(), self.surface.get_height()
            cr.set_source_rgba(0, 0, 0, .5)
            cr.rectangle(0, 0, sw, sh)
            cr.rectangle(l * sw, t * sh, (r - l) * sw, (b - t) * sh)
            cr.set_fill_rule(1)  # even-odd leaves the chosen area clear
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(1.5 / scale)
            cr.rectangle(l * sw, t * sh, (r - l) * sw, (b - t) * sh)
            cr.stroke()

    def step(self, d):
        if self.shown:
            self.index = (self.index + d) % len(self.shown)
            self.load_current()

    def show_grid(self):
        self.stop_slideshow()
        self.stack.set_visible_child_name('grid')

    # ---- edits
    def commit(self):
        save_edits(self.shown[self.index].path, self.edits)
        self.rerender()

    def rotate(self, d):
        if self.stack.get_visible_child_name() != 'viewer':
            return
        self.edits['rotate'] = (self.edits['rotate'] + d) % 360
        self.edits['crop'] = None
        self.commit()

    def on_bright(self, scale):
        if self.stack.get_visible_child_name() == 'viewer' and self.original and int(scale.get_value()) != self.edits['brightness']:
            self.edits['brightness'] = int(scale.get_value())
            self.commit()

    def revert(self):
        if self.stack.get_visible_child_name() == 'viewer':
            self.edits = dict(DEFAULT_EDITS)
            self.bright.set_value(0)
            self.crop_mode = False
            self.commit()

    def crop_square(self):
        if self.surface:
            w, h = self.surface.get_width(), self.surface.get_height()
            if self.crop_mode:
                self.edits['crop'] = None
                self.crop_mode = False
                self.rerender()
            s = min(w, h)
            l, t = (w - s) / 2 / w, (h - s) / 2 / h
            self.edits['crop'] = [l, t, 1 - l, 1 - t]
            self.commit()

    def toggle_crop(self):
        if not self.surface:
            return
        if self.crop_mode:
            if self.crop_rect:
                self.edits['crop'] = list(self.crop_rect)
            self.crop_mode, self.crop_rect = False, None
            self.commit()
        else:
            self.edits['crop'] = None
            self.crop_mode, self.crop_rect = True, None
            self.rerender()
            self.aw.say('Drag to choose the area, then press Crop again to apply.')

    def crop_update(self, dx, dy, final=False):
        if not (self.crop_mode and self.surface):
            return
        scale, ox, oy = self.layout()
        sx, sy = self.crop_start
        sw, sh = self.surface.get_width(), self.surface.get_height()

        def norm(x, y):
            return min(1, max(0, (x - ox) / scale / sw)), min(1, max(0, (y - oy) / scale / sh))
        a, b = norm(sx, sy), norm(sx + dx, sy + dy)
        self.crop_rect = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        self.canvas.queue_draw()

    def save_copy(self):
        if self.stack.get_visible_child_name() != 'viewer':
            return
        item = self.shown[self.index]
        try:
            out = save_edited_copy(item.path, self.edits, self.root / 'Edited')
            self.aw.say('Saved ' + str(out))
        except (OSError, ValueError) as error:
            self.aw.say('Could not save: ' + str(error))

    # ---- slideshow
    def toggle_slideshow(self):
        if self.slide:
            self.stop_slideshow()
            return
        if not self.shown:
            return
        if self.stack.get_visible_child_name() != 'viewer':
            self.open_item(0)
        self.slide = GLib.timeout_add_seconds(4, lambda: (self.step(1), True)[1])
        self.win.fullscreen()
        self.aw.say('Slideshow: press Escape to stop')

    def stop_slideshow(self):
        if self.slide:
            GLib.source_remove(self.slide)
            self.slide = 0
            self.win.unfullscreen()


def open_window(app, path=None):
    root = None
    if path and Path(path).is_dir():
        root = path
    p = Pictures(app, root)
    p.aw.present()
    if path and Path(path).is_file():
        def later():
            for i, it in enumerate(p.items):
                if it.path == Path(path):
                    p.shown = p.items
                    p.open_item(i)
            return False
        GLib.timeout_add(500, later)
    return p
