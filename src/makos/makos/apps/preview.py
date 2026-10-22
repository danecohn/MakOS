"""Preview: images and PDFs with zoom, rotation, page thumbnails, highlight/text-note annotations and export.

Annotations live in a sidecar JSON under the user's data folder (the original file is never modified).
PDF pages are rendered with poppler-utils (pdftoppm/pdfinfo). Without pypdf/poppler bindings the PDF is
render-only: annotations are not written into the PDF itself; "Export as PDF" rasterises pages instead.
"""
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .. import ui
from .base import AppWindow, data_dir, cache_dir, atomic_write, safe_filename

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tif', '.tiff', '.ico'}
MAX_PAGES = 400
RENDER_DPI = 130
HIGHLIGHT = '#ffe14d'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def kind_of(path):
    p = Path(path)
    if p.suffix.lower() == '.pdf':
        return 'pdf'
    if p.suffix.lower() in IMAGE_SUFFIXES or (mimetypes.guess_type(p.name)[0] or '').startswith('image/'):
        return 'image'
    return 'other'


# ------------------------------------------------------------------ rotation maths on normalised coordinates
def rot_point(p, degrees):
    x, y = p
    return {0: (x, y), 90: (1 - y, x), 180: (1 - x, 1 - y), 270: (y, 1 - x)}[degrees % 360]


def unrot_point(p, degrees):
    return rot_point(p, (360 - degrees) % 360)


def rect_norm(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


# ------------------------------------------------------------------ sidecar annotations
class Annotations:
    def __init__(self, source, root=None):
        self.source = str(Path(source).resolve())
        base = Path(root) if root else data_dir('preview', 'annotations')
        self.path = base / (hashlib.sha256(self.source.encode()).hexdigest()[:32] + '.json')
        self.data = {'version': 1, 'source': self.source, 'rotation': 0, 'pages': {}}
        try:
            raw = json.loads(self.path.read_text())
            if isinstance(raw, dict) and raw.get('version') == 1:
                self.data.update({'rotation': int(raw.get('rotation', 0)) % 360 // 90 * 90, 'pages': raw.get('pages', {}) if isinstance(raw.get('pages'), dict) else {}})
        except (OSError, ValueError, TypeError):
            pass

    def page(self, n):
        return self.data['pages'].get(str(n), [])

    def add(self, n, item):
        if item.get('type') == 'highlight':
            r = item.get('rect', [])
            if len(r) != 4 or not all(isinstance(v, (int, float)) for v in r):
                raise ValueError('bad highlight')
            item['rect'] = [min(1, max(0, v)) for v in r]
        elif item.get('type') == 'note':
            if len(item.get('pos', [])) != 2:
                raise ValueError('bad note')
            item['text'] = str(item.get('text', ''))[:2000]
        else:
            raise ValueError('unknown annotation type')
        self.data['pages'].setdefault(str(n), []).append(item)
        return item

    def remove_last(self, n):
        items = self.data['pages'].get(str(n))
        return items.pop() if items else None

    def remove_near(self, n, point, tolerance=.03):
        for item in reversed(self.data['pages'].get(str(n), [])):
            if item['type'] == 'highlight':
                x0, y0, x1, y1 = item['rect']
                hit = x0 - tolerance <= point[0] <= x1 + tolerance and y0 - tolerance <= point[1] <= y1 + tolerance
            else:
                hit = abs(item['pos'][0] - point[0]) < tolerance * 1.5 and abs(item['pos'][1] - point[1]) < tolerance * 1.5
            if hit:
                self.data['pages'][str(n)].remove(item)
                return item
        return None

    def count(self):
        return sum(len(v) for v in self.data['pages'].values())

    def save(self):
        atomic_write(self.path, json.dumps(self.data, indent=1), 0o600)


# ------------------------------------------------------------------ PDF through poppler-utils
def have_poppler(which=shutil.which):
    return bool(which('pdftoppm') and which('pdfinfo'))


def pdf_page_count(path):
    try:
        out = subprocess.run(['pdfinfo', '--', str(path)], capture_output=True, text=True, timeout=15, env={'LANG': 'C', 'PATH': os.environ.get('PATH', '/usr/bin')}).stdout
        m = re.search(r'^Pages:\s+(\d+)', out, re.M)
        return min(MAX_PAGES, int(m.group(1))) if m else 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 0


def render_pdf_page(path, page, dpi, out_png):
    """Render 1-based page to out_png (PNG). Returns True on success."""
    base = str(out_png)[:-4]
    try:
        subprocess.run(['pdftoppm', '-r', str(dpi), '-f', str(page), '-l', str(page), '-png', '-singlefile', '--', str(path), base], capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return Path(out_png).exists()


def load_page_image(path, page=0, dpi=RENDER_DPI, workdir=None):
    """PIL RGBA image of an image file or PDF page (0-based). Large images are limited to 6000 px."""
    from PIL import Image, ImageOps
    if kind_of(path) == 'pdf':
        work = Path(workdir or cache_dir('preview'))
        work.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(f'{Path(path).resolve()}:{os.path.getmtime(path)}:{page}:{dpi}'.encode()).hexdigest()[:24]
        png = work / (key + '.png')
        if not png.exists() and not render_pdf_page(path, page + 1, dpi, png):
            raise ValueError('The PDF page could not be rendered (is poppler-utils installed?)')
        with Image.open(png) as im:
            return im.convert('RGBA')
    Image.MAX_IMAGE_PIXELS = 120_000_000
    with Image.open(path) as im:
        im.seek(0)
        im = ImageOps.exif_transpose(im).convert('RGBA')
        im.thumbnail((6000, 6000))
        return im.copy()


def flatten(image, items):
    """Burn annotations (normalised to the unrotated page) into a copy of a PIL image."""
    from PIL import Image, ImageDraw, ImageFont
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w, h = base.size
    size = max(12, w // 55)
    try:
        font = ImageFont.truetype(FONT, size)
    except OSError:
        font = ImageFont.load_default()
    for it in items:
        if it['type'] == 'highlight':
            x0, y0, x1, y1 = it['rect']
            draw.rectangle((x0 * w, y0 * h, x1 * w, y1 * h), fill=(255, 225, 77, 110))
        else:
            x, y = it['pos'][0] * w, it['pos'][1] * h
            text = it.get('text', '')[:300]
            box = draw.multiline_textbbox((x + 4, y + 4), text, font=font)
            draw.rectangle((x, y, box[2] + 6, box[3] + 4), fill=(255, 248, 190, 235), outline=(150, 130, 40, 255))
            draw.multiline_text((x + 4, y + 4), text, fill=(40, 40, 30, 255), font=font)
    return Image.alpha_composite(base, layer)


def rotated(image, degrees):
    from PIL import Image
    return image.transpose({0: None, 90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}[degrees % 360]) if degrees % 360 else image


def export_png(path, page, dest, annotations, rotation=0, dpi=RENDER_DPI):
    img = rotated(flatten(load_page_image(path, page, dpi), annotations.page(page)), rotation)
    img.convert('RGB').save(dest, 'PNG')
    return dest


def export_pdf(path, dest, annotations, rotation=0):
    """Original bytes when nothing changed; otherwise a rasterised PDF of the annotated/rotated pages."""
    from PIL import Image
    if kind_of(path) == 'pdf' and annotations.count() == 0 and rotation % 360 == 0:
        shutil.copyfile(path, dest)
        return dest
    count = pdf_page_count(path) if kind_of(path) == 'pdf' else 1
    pages = [rotated(flatten(load_page_image(path, i), annotations.page(i)), rotation).convert('RGB') for i in range(max(1, count))]
    pages[0].save(dest, 'PDF', save_all=True, append_images=pages[1:], resolution=RENDER_DPI)
    return dest


def pil_to_cairo(image):
    buf = io.BytesIO()
    image.save(buf, 'PNG')
    buf.seek(0)
    return cairo.ImageSurface.create_from_png(buf)


MENU = [('File', [('Open…', 'open', '<Primary>o'), None, ('Export Page as PNG…', 'export_png', '<Primary>e'), ('Export as PDF…', 'export_pdf', '<Primary><Shift>e'), None, ('Close', 'close', '<Primary>w')]),
        ('Edit', [('Undo Annotation', 'undo_annot', '<Primary>z'), None, ('Highlight Tool', 'tool_highlight', '<Primary>h'), ('Note Tool', 'tool_note', '<Primary>t'), ('Pointer', 'tool_none', None)]),
        ('View', [('Zoom In', 'zoom_in', '<Primary>plus'), ('Zoom Out', 'zoom_out', '<Primary>minus'), ('Actual Size', 'zoom_actual', '<Primary>0'), ('Fit to Window', 'zoom_fit', '<Primary>9'), None,
                  ('Rotate Left', 'rotate_left', '<Primary>l'), ('Rotate Right', 'rotate_right', '<Primary>r'), None, ('Previous Page', 'prev', 'Page_Up'), ('Next Page', 'next', 'Page_Down')])]


class Preview:
    def __init__(self, app, path):
        self.path = Path(path)
        self.kind = kind_of(path)
        self.page, self.pages, self.zoom, self.fit, self.tool = 0, 1, 1.0, True, 'none'
        self.surface, self.drag, self.error = None, None, ''
        self.annots = Annotations(path)
        self.rotation = self.annots.data['rotation']
        self.aw = AppWindow(app, self.path.name, 920, 680, MENU)
        self.win = self.aw.win
        for name, fn in (('open', lambda: choose_and_open(app, self.win)), ('export_png', self.save_png), ('export_pdf', self.save_pdf), ('close', self.win.close),
                         ('undo_annot', self.undo), ('tool_highlight', lambda: self.set_tool('highlight')), ('tool_note', lambda: self.set_tool('note')), ('tool_none', lambda: self.set_tool('none')),
                         ('zoom_in', lambda: self.set_zoom(self.zoom * 1.25)), ('zoom_out', lambda: self.set_zoom(self.zoom / 1.25)), ('zoom_actual', lambda: self.set_zoom(1.0)),
                         ('zoom_fit', self.fit_window), ('rotate_left', lambda: self.rotate(-90)), ('rotate_right', lambda: self.rotate(90)),
                         ('prev', lambda: self.goto(self.page - 1)), ('next', lambda: self.goto(self.page + 1))):
            self.aw.action(name, fn)
        bar = ui.box(spacing=5, css='metal-toolbar')
        self.tool_buttons = {}
        for label, fn in (('−', lambda: self.set_zoom(self.zoom / 1.25)), ('+', lambda: self.set_zoom(self.zoom * 1.25)), ('Fit', self.fit_window), ('↺', lambda: self.rotate(-90)), ('↻', lambda: self.rotate(90))):
            bar.append(ui.button(label, fn))
        for key, label in (('highlight', 'Highlight'), ('note', 'Note')):
            b = Gtk.ToggleButton(label=label)
            b.connect('toggled', lambda btn, k=key: self.set_tool(k if btn.get_active() else 'none'))
            self.tool_buttons[key] = b
            bar.append(b)
        bar.append(ui.button('Export PNG', self.save_png))
        self.aw.body.append(bar)
        self.side = ui.box(True)
        self.thumbs = Gtk.ListBox(css_classes=['app-sidebar'])
        self.thumbs.connect('row-selected', lambda _b, r: r is not None and self.goto(r.index, from_list=True))
        self.side.append(ui.scroll(self.thumbs))
        self.side.set_size_request(150, -1)
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self.draw)
        self.scroller = ui.scroll(self.area)
        paned = Gtk.Paned(position=150, vexpand=True)
        paned.set_start_child(self.side)
        paned.set_end_child(self.scroller)
        paned.set_shrink_start_child(False)
        self.aw.body.append(paned)
        drag = Gtk.GestureDrag()
        drag.connect('drag-begin', self.on_begin)
        drag.connect('drag-update', self.on_update)
        drag.connect('drag-end', self.on_end)
        self.area.add_controller(drag)
        click = Gtk.GestureClick(button=3)
        click.connect('pressed', lambda _g, _n, x, y: self.remove_at(x, y))
        self.area.add_controller(click)
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect('drop', self.on_drop)
        self.win.add_controller(target)
        self.scroller.connect('notify::width', lambda *_: self.fit and self.fit_window())
        self.win.connect('close-request', lambda *_: (self.annots.save() if self.annots.count() or self.annots.path.exists() else None, False)[1])
        self.load_document()

    # ---- document
    def load_document(self):
        if self.kind == 'other':
            self.error = 'Preview opens images and PDF files.'
        elif self.kind == 'pdf':
            if not have_poppler():
                self.error = 'PDF display needs poppler-utils (pdftoppm, pdfinfo), which is not installed.'
            else:
                self.pages = pdf_page_count(self.path)
                if not self.pages:
                    self.error = 'This PDF could not be read.'
        if not self.error:
            self.build_thumbs()
            self.show_page()
        else:
            self.aw.say(self.error)
            self.area.queue_draw()

    def build_thumbs(self):
        ui.clear(self.thumbs)
        self.side.set_visible(self.pages > 1)
        for i in range(self.pages):
            row = Gtk.ListBoxRow()
            row.index = i
            col = ui.box(True, 2)
            pic = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN)
            pic.set_size_request(110, 140)
            row.pic = pic
            col.append(pic)
            col.append(Gtk.Label(label=str(i + 1), css_classes=['hint']))
            row.set_child(col)
            self.thumbs.append(row)
        if self.pages > 1:
            threading.Thread(target=self.make_thumbs, daemon=True).start()

    def make_thumbs(self):
        for i in range(self.pages):
            try:
                img = load_page_image(self.path, i, 30)
                img.thumbnail((220, 280))
                buf = io.BytesIO()
                img.convert('RGB').save(buf, 'PNG')
                data = buf.getvalue()
            except (OSError, ValueError):
                continue
            GLib.idle_add(lambda i=i, data=data: self.set_thumb(i, data))

    def set_thumb(self, index, data):
        row = self.thumbs.get_row_at_index(index)
        if row:
            row.pic.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
        return False

    def show_page(self):
        try:
            self.base = load_page_image(self.path, self.page)
        except (OSError, ValueError) as error:
            self.error = str(error)
            self.aw.say(self.error)
            return
        self.surface = pil_to_cairo(rotated(self.base, self.rotation))
        if self.fit:
            self.fit_window()
        else:
            self.apply_size()
        self.aw.say(f'{self.path.name}   page {self.page + 1} of {self.pages}   {self.base.width}×{self.base.height}   {int(self.zoom * 100)}%   {self.annots.count()} annotations (stored beside your data, not in the file)')

    def goto(self, n, from_list=False):
        if self.error or not 0 <= n < self.pages or n == self.page and self.surface:
            return
        self.page = n
        if not from_list:
            row = self.thumbs.get_row_at_index(n)
            if row:
                self.thumbs.select_row(row)
        self.show_page()

    # ---- geometry
    def display_size(self):
        return (self.surface.get_width() * self.zoom, self.surface.get_height() * self.zoom) if self.surface else (400, 300)

    def apply_size(self):
        w, h = self.display_size()
        self.area.set_content_width(int(w) + 20)
        self.area.set_content_height(int(h) + 20)
        self.area.queue_draw()

    def set_zoom(self, z):
        self.fit = False
        self.zoom = max(.05, min(8.0, z))
        self.apply_size()

    def fit_window(self):
        if not self.surface:
            return
        avail_w, avail_h = max(100, self.scroller.get_width() - 30), max(100, self.scroller.get_height() - 30)
        self.zoom = max(.05, min(avail_w / self.surface.get_width(), avail_h / self.surface.get_height(), 4.0))
        self.fit = True
        self.apply_size()

    def rotate(self, delta):
        self.rotation = (self.rotation + delta) % 360
        self.annots.data['rotation'] = self.rotation
        if self.surface:
            self.surface = pil_to_cairo(rotated(self.base, self.rotation))
            self.fit_window() if self.fit else self.apply_size()
        self.annots.save()

    def origin(self):
        w, h = self.display_size()
        return max(10, (self.area.get_width() - w) / 2), 10, w, h

    # ---- drawing
    def draw(self, _a, cr, width, height):
        cr.set_source_rgb(.55, .58, .62)
        cr.paint()
        if not self.surface:
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(20, 40)
            cr.show_text(self.error or 'Opening…')
            return
        ox, oy, w, h = self.origin()
        cr.save()
        cr.translate(ox, oy)
        cr.set_source_rgba(0, 0, 0, .35)
        cr.rectangle(3, 3, w, h)
        cr.fill()
        cr.scale(self.zoom, self.zoom)
        cr.set_source_surface(self.surface, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()
        for it in self.annots.page(self.page):
            self.draw_item(cr, it, ox, oy, w, h)
        if self.drag:
            x0, y0, x1, y1 = self.drag
            cr.set_source_rgba(1, .88, .3, .45)
            cr.rectangle(ox + min(x0, x1) * w, oy + min(y0, y1) * h, abs(x1 - x0) * w, abs(y1 - y0) * h)
            cr.fill()

    def draw_item(self, cr, it, ox, oy, w, h):
        if it['type'] == 'highlight':
            a, b = rot_point((it['rect'][0], it['rect'][1]), self.rotation), rot_point((it['rect'][2], it['rect'][3]), self.rotation)
            x0, y0, x1, y1 = rect_norm(a, b)
            cr.set_source_rgba(1, .88, .3, .45)
            cr.rectangle(ox + x0 * w, oy + y0 * h, (x1 - x0) * w, (y1 - y0) * h)
            cr.fill()
        else:
            x, y = rot_point(tuple(it['pos']), self.rotation)
            px, py = ox + x * w, oy + y * h
            cr.select_font_face('DejaVu Sans')
            cr.set_font_size(12)
            ext = cr.text_extents(it['text'] or '…')
            cr.set_source_rgba(1, .97, .75, .95)
            cr.rectangle(px, py, ext.width + 12, 22)
            cr.fill_preserve()
            cr.set_source_rgb(.6, .52, .15)
            cr.stroke()
            cr.set_source_rgb(.15, .15, .1)
            cr.move_to(px + 6, py + 15)
            cr.show_text((it['text'] or '…')[:80])

    # ---- annotation input
    def to_norm(self, x, y):
        ox, oy, w, h = self.origin()
        return min(1, max(0, (x - ox) / w)), min(1, max(0, (y - oy) / h))

    def set_tool(self, tool):
        self.tool = tool
        for k, b in self.tool_buttons.items():
            if b.get_active() != (k == tool):
                b.set_active(k == tool)
        self.aw.say({'highlight': 'Drag across the page to highlight.', 'note': 'Click where the note should go.', 'none': 'Pointer'}[tool])

    def on_begin(self, _g, x, y):
        if self.tool == 'highlight':
            p = self.to_norm(x, y)
            self.drag_start, self.drag = p, (*p, *p)

    def on_update(self, g, dx, dy):
        if self.drag:
            ok, sx, sy = g.get_start_point()
            p = self.to_norm(sx + dx, sy + dy)
            self.drag = (*self.drag_start, *p)
            self.area.queue_draw()

    def on_end(self, g, dx, dy):
        ok, sx, sy = g.get_start_point()
        if self.tool == 'highlight' and self.drag:
            end = self.to_norm(sx + dx, sy + dy)
            a, b = unrot_point(self.drag_start, self.rotation), unrot_point(end, self.rotation)
            x0, y0, x1, y1 = rect_norm(a, b)
            self.drag = None
            if x1 - x0 > .005 and y1 - y0 > .003:
                self.annots.add(self.page, {'type': 'highlight', 'rect': [x0, y0, x1, y1], 'color': HIGHLIGHT})
                self.annots.save()
            self.area.queue_draw()
        elif self.tool == 'note' and abs(dx) < 4 and abs(dy) < 4:
            self.ask_note(unrot_point(self.to_norm(sx, sy), self.rotation))

    def ask_note(self, pos):
        d = Gtk.Window(title='Note', transient_for=self.win, modal=True, default_width=320)
        col = ui.box(True, 8, 'sheet')
        entry = Gtk.Entry(placeholder_text='Note text')

        def ok(*_):
            if entry.get_text().strip():
                self.annots.add(self.page, {'type': 'note', 'pos': list(pos), 'text': entry.get_text().strip()})
                self.annots.save()
            d.destroy()
            self.area.queue_draw()
        entry.connect('activate', ok)
        col.append(entry)
        col.append(ui.button('Add Note', ok, 'suggested-action'))
        d.set_child(col)
        d.present()

    def remove_at(self, x, y):
        if self.annots.remove_near(self.page, unrot_point(self.to_norm(x, y), self.rotation)):
            self.annots.save()
            self.area.queue_draw()

    def undo(self):
        if self.annots.remove_last(self.page):
            self.annots.save()
            self.area.queue_draw()

    # ---- export / drop
    def save_png(self):
        self.export_dialog(f'{self.path.stem}-page{self.page + 1}.png', lambda dest: export_png(self.path, self.page, dest, self.annots, self.rotation))

    def save_pdf(self):
        self.export_dialog(f'{self.path.stem}.pdf', lambda dest: export_pdf(self.path, dest, self.annots, self.rotation))

    def export_dialog(self, name, work):
        dialog = Gtk.FileDialog(title='Export', initial_name=safe_filename(name))

        def chosen(d, r):
            try:
                f = d.save_finish(r)
            except GLib.Error:
                return
            if not f:
                return

            def go():
                try:
                    work(f.get_path())
                    msg = 'Exported ' + f.get_path()
                except (OSError, ValueError) as error:
                    msg = 'Export failed: ' + str(error)
                GLib.idle_add(lambda: (self.aw.say(msg), False)[1])
            threading.Thread(target=go, daemon=True).start()
        dialog.save(self.win, None, chosen)

    def on_drop(self, _t, value, _x, _y):
        files = value.get_files()
        for f in files:
            if f.get_path():
                open_window(self.win.get_application(), f.get_path())
        return bool(files)


def choose_and_open(app, parent=None):
    dialog = Gtk.FileDialog(title='Open an image or PDF')

    def picked(d, r):
        try:
            f = d.open_finish(r)
        except GLib.Error:
            return
        if f:
            open_window(app, f.get_path())
    dialog.open(parent, None, picked)


def open_window(app, path=None):
    if not path:
        choose_and_open(app)
        return None
    p = Preview(app, path)
    p.aw.present()
    return p
