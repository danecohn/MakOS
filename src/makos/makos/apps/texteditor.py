"""Text Editor: plain text with undo/redo, find/replace, atomic saves and unsaved-change protection."""
import re
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib, Pango
from .. import ui
from .base import AppWindow, confirm, atomic_write

MAX_BYTES = 8_000_000
MENU = [('File', [('New', 'new', '<Primary>n'), ('Open…', 'open', '<Primary>o'), None, ('Save', 'save', '<Primary>s'), ('Save As…', 'save_as', '<Primary><Shift>s'), None, ('Close', 'close', '<Primary>w')]),
        ('Edit', [('Undo', 'undo', '<Primary>z'), ('Redo', 'redo', '<Primary><Shift>z'), None, ('Cut', 'cut', '<Primary>x'), ('Copy', 'copy', '<Primary>c'), ('Paste', 'paste', '<Primary>v'), ('Select All', 'select_all', '<Primary>a'), None, ('Find and Replace…', 'find', '<Primary>f')]),
        ('View', [('Bigger Text', 'bigger', '<Primary>plus'), ('Smaller Text', 'smaller', '<Primary>minus'), ('Actual Size', 'actual', '<Primary>0'), ('Wrap Lines', 'wrap', None)])]


def find_all(text, query, case=False, regex=False, whole=False):
    """Non-overlapping (start, end) spans of query in text; invalid regex raises ValueError."""
    if not query:
        return []
    pattern = query if regex else re.escape(query)
    if whole:
        pattern = r'\b(?:' + pattern + r')\b'
    try:
        compiled = re.compile(pattern, 0 if case else re.IGNORECASE | re.UNICODE)
    except re.error as error:
        raise ValueError(str(error)) from error
    return [m.span() for m in compiled.finditer(text) if m.end() > m.start()][:100000]


def replace_all(text, query, replacement, case=False, regex=False, whole=False):
    spans = find_all(text, query, case, regex, whole)
    if not spans:
        return text, 0
    if regex:
        pattern = query if not whole else r'\b(?:' + query + r')\b'
        try:
            return re.sub(pattern, replacement, text, flags=0 if case else re.IGNORECASE | re.UNICODE), len(spans)
        except re.error as error:
            raise ValueError(str(error)) from error
    parts, last = [], 0
    for a, b in spans:
        parts.append(text[last:a])
        parts.append(replacement)
        last = b
    parts.append(text[last:])
    return ''.join(parts), len(spans)


def read_text_file(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('This file is larger than 8 MB; Text Editor will not load it.')
    data = path.read_bytes()
    if b'\x00' in data[:8192]:
        raise ValueError('This looks like a binary file, not text.')
    return data.decode('utf-8', errors='replace')


def statistics(text):
    return {'lines': text.count('\n') + 1 if text else 1, 'words': len(text.split()), 'chars': len(text)}


class Editor:
    def __init__(self, app, path=None):
        self.path = None
        self.size = 11
        self.saved_text = ''
        self.aw = AppWindow(app, 'Text Editor', 820, 600, MENU)
        self.win = self.aw.win
        self.buffer = Gtk.TextBuffer(enable_undo=True)
        self.view = Gtk.TextView(buffer=self.buffer, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, left_margin=10, right_margin=10, bottom_margin=8)
        self.find_bar = self.build_find()
        self.aw.body.append(self.find_bar)
        self.aw.body.append(ui.scroll(self.view))
        for name, fn in (('new', self.new), ('open', self.choose_open), ('save', self.save), ('save_as', self.save_as), ('close', self.win.close),
                         ('undo', lambda: self.buffer.undo()), ('redo', lambda: self.buffer.redo()),
                         ('cut', lambda: self.view.emit('cut-clipboard')), ('copy', lambda: self.view.emit('copy-clipboard')),
                         ('paste', lambda: self.view.emit('paste-clipboard')), ('select_all', lambda: self.view.emit('select-all', True)),
                         ('find', self.toggle_find), ('bigger', lambda: self.zoom(1)), ('smaller', lambda: self.zoom(-1)), ('actual', lambda: self.zoom(0)),
                         ('wrap', self.toggle_wrap)):
            self.aw.action(name, fn)
        self.buffer.connect('changed', lambda *_: self.refresh())
        self.buffer.connect('notify::can-undo', lambda *_: self.aw.enable('undo', self.buffer.get_can_undo()))
        self.buffer.connect('notify::can-redo', lambda *_: self.aw.enable('redo', self.buffer.get_can_redo()))
        self.aw.enable('undo', False)
        self.aw.enable('redo', False)
        self.win.connect('close-request', self.on_close)
        self.provider = Gtk.CssProvider()
        self.view.get_style_context().add_provider(self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.zoom(0)
        if path:
            self.load(path)
        self.refresh()

    # ---- document state
    def text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)

    @property
    def dirty(self):
        return self.text() != self.saved_text

    def refresh(self):
        s = statistics(self.text())
        self.win.set_title(('• ' if self.dirty else '') + (self.path.name if self.path else 'Untitled'))
        self.win._title.set_text(self.win.get_title())
        self.aw.say(f"{s['lines']} lines   {s['words']} words   {s['chars']} characters" + (f'   {self.path}' if self.path else ''))

    def load(self, path):
        try:
            text = read_text_file(path)
        except (OSError, ValueError) as error:
            ui.message(self.win.get_application(), 'Cannot open', str(error))
            return False
        self.path = Path(path)
        self.buffer.begin_irreversible_action()
        self.buffer.set_text(text)
        self.buffer.end_irreversible_action()
        self.saved_text = text
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.refresh()
        return True

    def write(self, target):
        try:
            atomic_write(target, self.text())
        except OSError as error:
            ui.message(self.win.get_application(), 'Cannot save', str(error))
            return False
        self.path = Path(target)
        self.saved_text = self.text()
        self.refresh()
        return True

    def save(self, then=None):
        if self.path:
            if self.write(self.path) and then:
                then()
        else:
            self.save_as(then)

    def save_as(self, then=None):
        dialog = Gtk.FileDialog(title='Save text')

        def chosen(d, r):
            try:
                f = d.save_finish(r)
            except GLib.Error:
                return
            if f and self.write(f.get_path()) and then:
                then()
        dialog.save(self.win, None, chosen)

    def new(self):
        open_window(self.win.get_application(), None)

    def choose_open(self):
        dialog = Gtk.FileDialog(title='Open a text file')

        def chosen(d, r):
            try:
                f = d.open_finish(r)
            except GLib.Error:
                return
            if f:
                if self.path is None and not self.dirty:
                    self.load(f.get_path())
                else:
                    open_window(self.win.get_application(), f.get_path())
        dialog.open(self.win, None, chosen)

    def on_close(self, *_):
        if not self.dirty:
            return False
        dialog = Gtk.AlertDialog(message='Save changes before closing?', detail='Your changes will be lost if you do not save them.', buttons=['Cancel', 'Discard', 'Save'], cancel_button=0, default_button=2)

        def done(d, r):
            try:
                choice = d.choose_finish(r)
            except GLib.Error:
                return
            if choice == 1:
                self.saved_text = self.text()
                self.win.close()
            elif choice == 2:
                self.save(then=self.win.close)
        dialog.choose(self.win, None, done)
        return True

    # ---- view
    def zoom(self, delta):
        self.size = 11 if delta == 0 else max(7, min(40, self.size + delta))
        self.provider.load_from_string('textview { font-size: %dpx; }' % self.size)

    def toggle_wrap(self):
        self.view.set_wrap_mode(Gtk.WrapMode.NONE if self.view.get_wrap_mode() != Gtk.WrapMode.NONE else Gtk.WrapMode.WORD_CHAR)

    # ---- find / replace
    def build_find(self):
        bar = Gtk.Revealer(reveal_child=False)
        row = ui.box(spacing=6, css='metal-toolbar')
        self.find_entry = Gtk.SearchEntry(placeholder_text='Find', hexpand=True)
        self.replace_entry = Gtk.Entry(placeholder_text='Replace with', hexpand=True)
        self.case = Gtk.CheckButton(label='Match case')
        self.regex = Gtk.CheckButton(label='Regex')
        self.find_info = Gtk.Label(label='', css_classes=['hint'])
        for w in (self.find_entry, self.replace_entry, self.case, self.regex, ui.button('Previous', lambda: self.step(-1)), ui.button('Next', lambda: self.step(1)),
                  ui.button('Replace', self.replace_one), ui.button('Replace All', self.replace_everything), self.find_info):
            row.append(w)
        self.find_entry.connect('search-changed', lambda *_: self.step(0))
        self.find_entry.connect('activate', lambda *_: self.step(1))
        bar.set_child(row)
        return bar

    def toggle_find(self):
        show = not self.find_bar.get_reveal_child()
        self.find_bar.set_reveal_child(show)
        if show:
            self.find_entry.grab_focus()
        else:
            self.view.grab_focus()

    def spans(self):
        try:
            self.find_info.set_text('')
            return find_all(self.text(), self.find_entry.get_text(), self.case.get_active(), self.regex.get_active())
        except ValueError:
            self.find_info.set_text('Invalid pattern')
            return []

    def step(self, direction):
        spans = self.spans()
        self.find_info.set_text(f'{len(spans)} found' if spans or not self.find_entry.get_text() else 'Not found')
        if not spans:
            return
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()
        sel = self.buffer.get_selection_bounds()
        start = sel[0].get_offset() if sel else cursor
        if direction == 0:
            pick = next((s for s in spans if s[0] >= start), spans[0])
        elif direction > 0:
            pick = next((s for s in spans if s[0] > start), spans[0])
        else:
            pick = next((s for s in reversed(spans) if s[0] < start), spans[-1])
        a, b = (self.buffer.get_iter_at_offset(pick[0]), self.buffer.get_iter_at_offset(pick[1]))
        self.buffer.select_range(a, b)
        self.view.scroll_to_iter(a, 0.1, False, 0, 0)

    def replace_one(self):
        sel = self.buffer.get_selection_bounds()
        if sel and (sel[1].get_offset() - sel[0].get_offset()) > 0 and self.buffer.get_text(sel[0], sel[1], True):
            span = (sel[0].get_offset(), sel[1].get_offset())
            if span in self.spans():
                self.buffer.delete(sel[0], sel[1])
                self.buffer.insert_at_cursor(self.replace_entry.get_text())
        self.step(1)

    def replace_everything(self):
        try:
            out, count = replace_all(self.text(), self.find_entry.get_text(), self.replace_entry.get_text(), self.case.get_active(), self.regex.get_active())
        except (ValueError, re.error):
            self.find_info.set_text('Invalid pattern')
            return
        if count:
            self.buffer.begin_user_action()
            self.buffer.delete(self.buffer.get_start_iter(), self.buffer.get_end_iter())
            self.buffer.insert(self.buffer.get_start_iter(), out)
            self.buffer.end_user_action()
        self.find_info.set_text(f'{count} replaced')


def open_window(app, path=None):
    editor = Editor(app, path)
    editor.aw.present()
    return editor
