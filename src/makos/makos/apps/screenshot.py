"""Screenshot: whole screen, selection or one window, with a delay; saves to Pictures/Screenshots.

KWin only lets authorised clients call ScreenShot2, and the shell is the authorised one. The app
therefore asks the shell (org.makos.Control Action "capture:...") to write a PNG into a private
runtime folder and then moves it. KWin's "hide caller" option is explicitly turned off in
makos.capture so the shell's own windows and this app's results are included as they appear.
"""
import json
import cairo
import os
import re
import time
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .. import ui, common
from .base import AppWindow, notify

WINDOW_ID = re.compile(r'^[{}0-9a-fA-F-]{1,64}$')
MODES = ('full', 'selection', 'window')


def shots_dir():
    return common.RUNTIME / 'shots'


def pictures_dir():
    found = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    return Path(found) if found else Path.home() / 'Pictures'


def filename_for(moment=None):
    return time.strftime('Screenshot %Y-%m-%d %H.%M.%S.png', moment or time.localtime())


def unique_path(folder, name):
    folder = Path(folder)
    target = folder / name
    n = 2
    while target.exists():
        target = folder / f'{Path(name).stem} ({n}).png'
        n += 1
    return target


def valid_dest(dest):
    """The shell writes only plain .png files directly inside its private runtime shots folder."""
    p = Path(dest)
    return p.suffix == '.png' and p.parent == shots_dir() and p.name == os.path.basename(dest) and '..' not in p.parts


def scale_rect(rect, widget_size, image_size):
    """Widget-space (x, y, w, h) -> clamped image-space (left, top, right, bottom)."""
    x, y, w, h = rect
    sx, sy = image_size[0] / max(1, widget_size[0]), image_size[1] / max(1, widget_size[1])
    left, right = sorted((x * sx, (x + w) * sx))
    top, bottom = sorted((y * sy, (y + h) * sy))
    box = (max(0, round(left)), max(0, round(top)), min(image_size[0], round(right)), min(image_size[1], round(bottom)))
    return box if box[2] - box[0] >= 2 and box[3] - box[1] >= 2 else None


def crop_file(src, box, dest):
    from PIL import Image
    with Image.open(src) as image:
        image.crop(box).save(dest, 'PNG')
    return dest


def parse_capture(name):
    """capture:<mode>:<window id or ->:<dest> -> (mode, id|None, dest) or None."""
    parts = name.split(':', 3)
    if len(parts) != 4 or parts[0] != 'capture' or parts[1] not in ('full', 'window'):
        return None
    ident = parts[2] if parts[2] != '-' else None
    if parts[1] == 'window' and not (ident and WINDOW_ID.match(ident)):
        return None
    return (parts[1], ident, parts[3]) if valid_dest(parts[3]) else None


def shell_action(shell, name):
    """Runs inside the shell (the authorised KWin ScreenShot2 client). Called from Shell.action."""
    if name.startswith('screenshot:'):
        mode = name.split(':', 1)[1]
        if mode in MODES:
            from . import spawn
            spawn('screenshot', '--' + mode)
        return
    parsed = parse_capture(name)
    if not parsed:
        return
    mode, ident, dest = parsed
    from .. import capture

    def work():
        surface = capture.window(shell.bus, ident) if mode == 'window' else capture.workspace(shell.bus)
        shots_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = dest + '.part'
        surface.write_to_png(temp)
        os.replace(temp, dest)
    shell.background(work, lambda _result: None)


def request_capture(mode, ident, done, timeout=12):
    """Ask the shell for a capture; done(path or None). Falls back to a direct call without a shell."""
    shots_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    dest = str(shots_dir() / f'cap-{os.getpid()}-{int(time.time() * 1000)}.png')
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        owner = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'NameHasOwner', GLib.Variant('(s)', ('org.makos.Shell',)), None, Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        if owner:
            bus.call_sync('org.makos.Shell', '/Control', 'org.makos.Control', 'Action', GLib.Variant('(s)', (f'capture:{mode}:{ident or "-"}:{dest}',)), None, Gio.DBusCallFlags.NONE, 3000, None)
        else:
            from .. import capture
            surface = capture.window(bus, ident) if mode == 'window' else capture.workspace(bus)
            surface.write_to_png(dest)
    except (GLib.Error, ValueError, OSError):
        done(None)
        return
    start = time.monotonic()

    def poll():
        if os.path.exists(dest):
            done(dest)
            return False
        if time.monotonic() - start > timeout:
            done(None)
            return False
        return True
    if poll():
        GLib.timeout_add(100, poll)


def window_list():
    """[(id, caption)] of normal windows from the shell; empty when no shell."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        state = json.loads(bus.call_sync('org.makos.Shell', '/Control', 'org.makos.Control', 'State', None, None, Gio.DBusCallFlags.NONE, 1500, None).unpack()[0])
        wins = state.get('windows')
        wins = wins.get('windows', []) if isinstance(wins, dict) else wins or []
        return [(w['id'], w.get('caption') or w.get('cls', 'Window')) for w in wins if w.get('id') and not w.get('skip') and not str(w.get('cls', '')).startswith('org.makos.Shell')]
    except (GLib.Error, ValueError, TypeError, KeyError):
        return []


MENU = [('File', [('Capture', 'capture', '<Primary>Return'), None, ('Close', 'close', '<Primary>w')]),
        ('Capture', [('Entire Screen', 'mode_full', '<Primary><Shift>3'), ('Selection', 'mode_selection', '<Primary><Shift>4'), ('Window', 'mode_window', '<Primary><Shift>5')])]


class Screenshot:
    def __init__(self, app, immediate=None):
        self.app = app
        self.mode = 'full'
        self.last = None
        self.windows = []
        self.aw = AppWindow(app, 'Screenshot', 460, 330, MENU)
        self.win = self.aw.win
        for name, fn in (('capture', self.start), ('close', self.win.close), ('mode_full', lambda: self.set_mode('full')),
                         ('mode_selection', lambda: self.set_mode('selection')), ('mode_window', lambda: self.set_mode('window'))):
            self.aw.action(name, fn)
        col = ui.box(True, 10, 'sheet')
        col.append(Gtk.Label(label='Take a picture of your screen', xalign=0, css_classes=['hero']))
        self.buttons = {}
        row = ui.box(spacing=6)
        group = None
        for key, label in (('full', 'Entire Screen'), ('selection', 'Selection'), ('window', 'Window')):
            b = Gtk.ToggleButton(label=label, group=group)
            group = group or b
            b.connect('toggled', lambda btn, k=key: btn.get_active() and self.set_mode(k))
            self.buttons[key] = b
            row.append(b)
        col.append(row)
        delay = ui.box(spacing=8)
        delay.append(Gtk.Label(label='Delay (seconds)'))
        self.delay = Gtk.SpinButton.new_with_range(0, 30, 1)
        delay.append(self.delay)
        col.append(delay)
        self.window_pick = Gtk.DropDown.new_from_strings(['(refresh to list windows)'])
        self.window_pick.set_visible(False)
        col.append(self.window_pick)
        col.append(ui.button('Capture', self.start, 'suggested-action'))
        self.result = Gtk.Label(label='', xalign=0, wrap=True, selectable=True, css_classes=['hint'])
        col.append(self.result)
        self.aw.body.append(col)
        self.buttons['full'].set_active(True)
        self.aw.say('Saves to ' + str(pictures_dir() / 'Screenshots'))
        if immediate in ('--full', '--selection', '--window'):
            self.set_mode(immediate[2:])
            GLib.idle_add(lambda: (self.start(), False)[1])

    def set_mode(self, mode):
        self.mode = mode
        if self.buttons[mode].get_active() is False:
            self.buttons[mode].set_active(True)
        self.window_pick.set_visible(mode == 'window')
        if mode == 'window':
            self.windows = window_list()
            self.window_pick.set_model(Gtk.StringList.new([c[:60] for _i, c in self.windows] or ['No windows available']))

    def start(self):
        seconds = int(self.delay.get_value())
        ident = None
        if self.mode == 'window':
            index = self.window_pick.get_selected()
            if not self.windows or index >= len(self.windows):
                self.result.set_text('Choose a window first.')
                return
            ident = self.windows[index][0]
        self.win.set_visible(False)  # the shot must not contain this window
        GLib.timeout_add(max(450, seconds * 1000), lambda: (self.take(ident), False)[1])

    def take(self, ident):
        mode = 'window' if self.mode == 'window' else 'full'
        request_capture(mode, ident, lambda path: self.captured(path))

    def captured(self, path):
        if not path:
            self.win.set_visible(True)
            self.result.set_text('The compositor refused or could not take the picture. Screenshots need a running MakOS shell.')
            return
        if self.mode == 'selection':
            Selector(self.app, path, lambda box: self.finish(path, box))
        else:
            self.finish(path, None)

    def finish(self, path, box):
        self.win.set_visible(True)
        if box == 'cancel':
            self.result.set_text('Selection cancelled.')
            return
        folder = pictures_dir() / 'Screenshots'
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target = unique_path(folder, filename_for())
            if box:
                crop_file(path, box, target)
            else:
                os.replace(path, target) if os.stat(path).st_dev == os.stat(folder).st_dev else target.write_bytes(Path(path).read_bytes())
            for leftover in (path,):
                if os.path.exists(leftover):
                    os.unlink(leftover)  # the private temp capture, never a user file
        except (OSError, ValueError) as error:
            self.result.set_text('Could not save: ' + str(error))
            return
        self.last = target
        self.result.set_text('Saved ' + str(target))
        notify('Screenshot saved', target.name, 'makos-screenshot', 'Screenshot')


class Selector:
    """Full-screen frozen picture; drag a rectangle, Enter or release to keep it, Escape to cancel."""

    def __init__(self, app, path, done):
        self.path, self.done, self.rect, self.start = path, done, None, None
        self.win = Gtk.Window(application=app, title='Select area', fullscreened=True, decorated=False)
        picture = Gtk.Picture.new_for_filename(path)
        picture.set_content_fit(Gtk.ContentFit.FILL)
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self.draw)
        overlay = Gtk.Overlay(child=picture)
        overlay.add_overlay(self.area)
        self.win.set_child(overlay)
        drag = Gtk.GestureDrag()
        drag.connect('drag-begin', lambda _g, x, y: setattr(self, 'start', (x, y)))
        drag.connect('drag-update', lambda _g, dx, dy: self.update(dx, dy))
        drag.connect('drag-end', lambda _g, dx, dy: (self.update(dx, dy), self.accept()))
        self.area.add_controller(drag)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.key)
        self.win.add_controller(keys)
        self.area.set_cursor(Gdk.Cursor.new_from_name('crosshair'))
        self.win.present()

    def update(self, dx, dy):
        if self.start:
            self.rect = (self.start[0], self.start[1], dx, dy)
            self.area.queue_draw()

    def draw(self, _a, cr, w, h):
        cr.set_source_rgba(0, 0, 0, .35)
        cr.paint()
        if self.rect:
            x, y, rw, rh = self.rect
            cr.set_operator(cairo.Operator.CLEAR)
            cr.rectangle(x, y, rw, rh)
            cr.fill()
            cr.set_operator(cairo.Operator.OVER)
            cr.set_source_rgba(1, 1, 1, .9)
            cr.set_line_width(1)
            cr.rectangle(x + .5, y + .5, rw, rh)
            cr.stroke()

    def key(self, _c, keyval, *_):
        if keyval == Gdk.KEY_Escape:
            self.finish('cancel')
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.accept()
        return True

    def accept(self):
        if not self.rect:
            return
        from PIL import Image
        with Image.open(self.path) as im:
            size = im.size
        box = scale_rect(self.rect, (self.area.get_width(), self.area.get_height()), size)
        self.finish(box or 'cancel')

    def finish(self, result):
        self.win.destroy()
        self.done(result)


def open_window(app, path=None):
    s = Screenshot(app, path if isinstance(path, str) and path.startswith('--') else None)
    s.aw.present()
    return s
