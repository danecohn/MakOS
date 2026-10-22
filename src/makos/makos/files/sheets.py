"""Modal sheets: confirmations, naming, progress, conflict resolution, errors, connect-to-server."""
import threading

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .. import ui
from . import model, network, ops, widgets


def make_sheet(files, title, width=460, height=200, modal=True):
    w = ui.window(files.app, title, width, height)
    w.set_transient_for(files.win)
    w.set_modal(modal)
    w.set_resizable(False)
    w.add_css_class('files-sheet')
    keys = Gtk.EventControllerKey()
    keys.connect('key-pressed', lambda _c, k, _c2, _s: (w.close(), True)[1] if k == Gdk.KEY_Escape else False)
    w.add_controller(keys)
    return w


def _buttons(*specs):
    row = ui.box(spacing=10)
    row.set_halign(Gtk.Align.END)
    out = []
    for label, cb, css in specs:
        b = ui.button(label, cb, css)
        row.append(b)
        out.append(b)
    return row, out


def confirm(files, title, body, confirm_label, on_yes, destructive=False, detail=None, icon='trash-full'):
    w = make_sheet(files, title, 460, 220)
    col = ui.box(True, 12, 'sheet')
    top = ui.box(spacing=14)
    top.append(widgets.make_icon(icon, 48))
    text = ui.box(True, 6)
    text.append(Gtk.Label(label=title, xalign=0, wrap=True, css_classes=['sheet-title']))
    text.append(Gtk.Label(label=body, xalign=0, wrap=True, max_width_chars=44))
    if detail:
        text.append(Gtk.Label(label=detail, xalign=0, wrap=True, max_width_chars=44, css_classes=['subtitle']))
    top.append(text)
    col.append(top)

    def yes():
        w.close()
        on_yes()
    row, btns = _buttons(('Cancel', w.close, None), (confirm_label, yes, 'destructive-action' if destructive else 'suggested-action'))
    col.append(row)
    w.set_child(col)
    w.present()
    # Cancel is the default so Return never destroys data by accident.
    btns[0].grab_focus()
    return w


def ask_name(files, title, prompt, initial, ok_label, on_ok, select_stem=True):
    w = make_sheet(files, title, 440, 180)
    col = ui.box(True, 10, 'sheet')
    col.append(Gtk.Label(label=prompt, xalign=0, wrap=True))
    entry = Gtk.Entry(text=initial, activates_default=True)
    error = Gtk.Label(xalign=0, wrap=True, css_classes=['error-label'])
    col.append(entry)
    col.append(error)

    def apply():
        name = entry.get_text()
        problem = model.valid_name(name)
        if problem:
            error.set_text(problem)
            return
        w.close()
        on_ok(name.strip())
    row, _ = _buttons(('Cancel', w.close, None), (ok_label, apply, 'suggested-action'))
    col.append(row)
    entry.connect('activate', lambda *_: apply())
    w.set_child(col)
    w.present()
    entry.grab_focus()
    stem = model.split_name(initial)[0] if select_stem else initial
    entry.select_region(0, len(stem))
    return w


def message(files, title, body, lines=None):
    w = make_sheet(files, title, 520, 260, modal=False)
    col = ui.box(True, 10, 'sheet')
    col.append(Gtk.Label(label=title, xalign=0, css_classes=['sheet-title']))
    col.append(Gtk.Label(label=body, xalign=0, wrap=True, max_width_chars=60, selectable=True))
    if lines:
        text = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=False, cursor_visible=False)
        text.get_buffer().set_text('\n'.join(lines[:60]) + (f'\n… and {len(lines) - 60} more' if len(lines) > 60 else ''))
        sc = ui.scroll(text, None, 110)
        col.append(sc)
    row, _ = _buttons(('OK', w.close, 'suggested-action'))
    col.append(row)
    w.set_child(col)
    w.present()
    return w


# ---------------------------------------------------------------- progress

class ProgressSheet:
    """Shown only when a job runs longer than ``delay`` ms. Has a Cancel button."""

    def __init__(self, files, job, delay=450):
        self.files, self.job, self.win = files, job, None
        self.closed = False
        job.listeners.append(self._notify)
        GLib.timeout_add(delay, self._show)

    def _notify(self, job):
        GLib.idle_add(self._update)

    def _show(self):
        if self.closed or self.job.state in ('done', 'failed', 'cancelled'):
            return False
        w = make_sheet(self.files, self.job.label, 420, 150, modal=False)
        col = ui.box(True, 10, 'sheet')
        self.title = Gtk.Label(xalign=0, css_classes=['sheet-title'])
        self.bar = Gtk.ProgressBar(show_text=False)
        self.detail = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=['subtitle'])
        col.append(self.title)
        col.append(self.bar)
        col.append(self.detail)
        row, _ = _buttons(('Cancel', self.job.cancel, None))
        col.append(row)
        w.set_child(col)
        w.connect('close-request', self._close_request)
        self.win = w
        w.present()
        self._update()
        return False

    def _close_request(self, *_):
        if self.job.state in ('queued', 'running'):
            self.job.cancel()
        self.closed = True
        return False

    def _update(self):
        job = self.job
        if self.win is None:
            return False
        if job.state in ('done', 'failed', 'cancelled'):
            self.closed = True
            self.win.close()
            return False
        names = {'copy': 'Copying', 'move': 'Moving', 'duplicate': 'Duplicating', 'delete': 'Deleting', 'trash': 'Moving to Trash',
                 'compress': 'Compressing', 'extract': 'Extracting', 'empty-trash': 'Emptying Trash', 'restore': 'Putting back'}
        n = len(job.sources) or job.total_items or 1
        self.title.set_text(f'{names.get(job.kind, job.label)} {n} item' + ('' if n == 1 else 's') + '…')
        if job.total_bytes or job.total_items:
            self.bar.set_fraction(job.fraction)
        else:
            self.bar.pulse()
        extra = f'{model.human_size(job.done_bytes)} of {model.human_size(job.total_bytes)}' if job.total_bytes else ''
        self.detail.set_text((job.current + ('  ·  ' + extra if extra else '')) if job.current else extra)
        return False


# ---------------------------------------------------------------- conflicts

def _describe_file(f):
    try:
        info = f.query_info('standard::size,standard::type,time::modified,standard::display-name', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
        dt = info.get_modification_date_time()
        size = '' if info.get_file_type() == Gio.FileType.DIRECTORY else model.human_size(info.get_size()) + '  ·  '
        return f'{size}modified {model.format_date(dt.to_unix()) if dt else "--"}', info.get_file_type() == Gio.FileType.DIRECTORY
    except GLib.Error:
        return '', False


def ask_conflict(files):
    """Return an ``ask(job, src, dst)`` for ops.Engine: blocks the worker thread until the user answers."""
    def ask(job, src, dst):
        done = threading.Event()
        answer = []

        def show():
            w = make_sheet(files, 'Item already exists', 500, 250, modal=True)
            col = ui.box(True, 10, 'sheet')
            name = ops.display(dst)
            s_text, s_dir = _describe_file(src)
            d_text, d_dir = _describe_file(dst)
            col.append(Gtk.Label(label=f'“{name}” already exists in this location.', xalign=0, wrap=True, css_classes=['sheet-title']))
            if s_dir and d_dir:
                col.append(Gtk.Label(label='Replace will merge the folders: items with the same name are replaced; nothing else is removed.',
                                     xalign=0, wrap=True, max_width_chars=58, css_classes=['subtitle']))
            col.append(Gtk.Label(label=f'Existing item:  {d_text}', xalign=0))
            col.append(Gtk.Label(label=f'New item:       {s_text}', xalign=0))
            every = Gtk.CheckButton(label='Apply to all remaining items')
            col.append(every)

            def reply(res):
                if not answer:
                    answer.append((res, every.get_active()))
                    if res is None:
                        job.cancel()
                    done.set()
                w.close()
            row, _ = _buttons(('Stop', lambda: reply(None), None), ('Skip', lambda: reply(ops.SKIP), None),
                              ('Keep Both', lambda: reply(ops.KEEP_BOTH), None), ('Replace', lambda: reply(ops.REPLACE), 'suggested-action'))
            col.append(row)
            w.connect('close-request', lambda *_: (reply(None), False)[1])
            w.set_child(col)
            w.present()
            return False
        GLib.idle_add(show)
        while not done.wait(0.25):
            if job.cancelled:
                break
        if not answer:
            return ops.SKIP, False
        res, every = answer[0]
        return (res or ops.SKIP), every
    return ask


# ---------------------------------------------------------------- connect to server

def connect_server(files, on_connect):
    w = make_sheet(files, 'Connect to Server', 500, 330)
    col = ui.box(True, 10, 'sheet')
    col.append(Gtk.Label(label='Server address', xalign=0, css_classes=['sheet-title']))
    col.append(Gtk.Label(label='Examples: smb://server/share   sftp://user@host/folder   davs://host/remote.php/dav   ftp://host',
                         xalign=0, wrap=True, max_width_chars=56, css_classes=['subtitle']))
    entry = Gtk.Entry(placeholder_text='smb://server/share', activates_default=True)
    error = Gtk.Label(xalign=0, wrap=True, css_classes=['error-label'])
    col.append(entry)
    col.append(error)
    col.append(Gtk.Label(label='Favorite servers', xalign=0, css_classes=['section-title']))
    favs = ui.box(True, 2)
    for s in files.prefs['servers'][:8]:
        favs.append(ui.button(s, lambda s=s: entry.set_text(s)))
    col.append(favs)
    remember = Gtk.CheckButton(label='Add to favorite servers', active=True)
    col.append(remember)

    def go():
        try:
            uri = network.normalize_server(entry.get_text())
        except network.ServerError as exc:
            error.set_text(str(exc))
            return
        if remember.get_active() and uri not in files.prefs['servers']:
            files.prefs['servers'] = ([uri] + files.prefs['servers'])[:20]
            files.save_prefs()
        w.close()
        on_connect(uri)
    row, _ = _buttons(('Cancel', w.close, None), ('Connect', go, 'suggested-action'))
    col.append(row)
    entry.connect('activate', lambda *_: go())
    w.set_child(col)
    w.present()
    entry.grab_focus()
    return w
