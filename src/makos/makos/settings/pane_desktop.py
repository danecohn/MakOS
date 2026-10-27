"""Desktop & Screen Saver: wallpaper picker (shipped images + the user's pictures) and screen lock after idle."""
import gi

gi.require_version('Gtk', '4.0')
from pathlib import Path

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from .. import ui
from ..backends import security, wallpapers
from . import widgets as W


def _thumb(path, w=150, h=94):
    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), w, h, True)
    return pix


def build(col, ctx):
    d = ctx.data
    s = W.section(col, 'Wallpaper')
    current = wallpapers.current(d)
    label = Gtk.Label(label='Current: ' + (current.name if current else 'none (no wallpaper images installed)'), xalign=0, css_classes=['subtitle'])
    s.append(label)
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=5, column_spacing=8, row_spacing=8, homogeneous=False)
    s.append(flow)

    def choose(path):
        ctx.do(wallpapers.set_wallpaper, str(path), ok='Wallpaper changed.',
               done=lambda r: label.set_text('Current: ' + Path(path).name) if r and r.get('wallpaper') else None)

    def add(path):
        try:
            pix = _thumb(path)
        except GLib.Error:
            return
        img = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pix))
        img.set_size_request(150, 94)
        img.set_content_fit(Gtk.ContentFit.COVER)
        cell = ui.box(True, 3)
        cell.append(img)
        cell.append(Gtk.Label(label=Path(path).stem[:22], css_classes=['subtitle']))
        b = ui.button('', lambda p=path: choose(p), 'settings-tile')
        b.set_child(cell)
        b.set_tooltip_text(str(path))
        flow.append(b)

    def load():
        return wallpapers.builtin() + wallpapers.user_images()

    def render(_box, paths):
        for p in paths[:40]:
            add(p)
        if not paths:
            W.note(s, 'No wallpaper images were found. Add pictures to ~/Pictures/Wallpapers or choose a file.')
    W.loading(s, load, lambda box, paths: render(box, paths))

    def pick():
        dialog = Gtk.FileDialog(title='Choose a wallpaper')
        flt = Gtk.FileFilter(name='Images')
        for pattern in ('*.png', '*.jpg', '*.jpeg', '*.webp'):
            flt.add_pattern(pattern)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        dialog.set_filters(store)

        def picked(dlg, result):
            try:
                f = dlg.open_finish(result)
            except GLib.Error:
                return
            if f and f.get_path():
                choose(f.get_path())
        dialog.open(ctx.window, None, picked)
    row = ui.box(spacing=10)
    row.append(ui.button('Choose Picture…', pick))
    row.append(ui.button('Use Default', lambda: ctx.do(wallpapers.set_wallpaper, '', ok='Default wallpaper restored.',
                                                       done=lambda _r: label.set_text('Current: default'))))
    s.append(row)

    s = W.section(col, 'Screen saver and lock')
    W.note(s, 'VigilOS has no animated screen savers. After the idle time the screen is locked, and your display power settings decide when it turns off.')
    lock = security.lock_settings()
    state = {'timeout': lock['timeout_min']}
    W.switch_row(s, 'Lock the screen after being idle', lock['auto_lock'], lambda v: ctx.do(security.set_lock, auto_lock=v, ok='Saved.'))
    W.choice_row(s, 'Idle time', [(m, f'{m} minutes' if m > 1 else '1 minute') for m in (1, 2, 5, 10, 15, 30, 60)] if lock['timeout_min'] in (1, 2, 5, 10, 15, 30, 60)
                 else [(lock['timeout_min'], f"{lock['timeout_min']} minutes")] + [(m, f'{m} minutes') for m in (1, 2, 5, 10, 15, 30, 60)],
                 lock['timeout_min'], lambda v: ctx.do(security.set_lock, timeout_min=v, ok='Idle time changed.'))
    W.choice_row(s, 'Require password', [(0, 'Immediately'), (5, 'After 5 seconds'), (30, 'After 30 seconds'), (60, 'After 1 minute')],
                 lock['grace_seconds'] if lock['grace_seconds'] in (0, 5, 30, 60) else 5,
                 lambda v: ctx.do(security.set_lock, grace_seconds=v, ok='Saved.'),
                 hint='Your password is asked for by the lock screen itself, never by Settings.')
    W.button_row(s, 'Lock now', 'Lock Screen', lambda: ctx.do(security.lock_now, ok='Locking…'))
