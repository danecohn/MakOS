"""Notes: plain-text notes grouped in folders (one directory per folder, one file per note)."""
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .. import ui, common
from .base import AppWindow, data_dir, atomic_write, confirm

DEFAULT_FOLDER, TRASH_FOLDER = 'Notes', 'Recently Deleted'
FOLDER_RE = re.compile(r'^[^/\\.\x00][^/\\\x00]{0,60}$')
NOTE_RE = re.compile(r'^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}\.txt$')


@dataclass
class Note:
    folder: str
    ident: str
    title: str
    mtime: float
    preview: str


def title_of(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:60]
    return 'New Note'


class NotesStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_dir('notes')
        (self.root / DEFAULT_FOLDER).mkdir(parents=True, exist_ok=True)

    def _folder(self, name):
        if not FOLDER_RE.match(name or ''):
            raise ValueError('Invalid folder name')
        return self.root / name

    def _file(self, folder, ident):
        if not NOTE_RE.match(ident or ''):
            raise ValueError('Invalid note')
        return self._folder(folder) / ident

    def folders(self):
        names = sorted((p.name for p in self.root.iterdir() if p.is_dir() and FOLDER_RE.match(p.name)), key=str.casefold)
        return [DEFAULT_FOLDER] + [n for n in names if n not in (DEFAULT_FOLDER, TRASH_FOLDER)] + ([TRASH_FOLDER] if TRASH_FOLDER in names else [])

    def create_folder(self, name):
        name = name.strip()
        if name in (TRASH_FOLDER,):
            raise ValueError('Reserved folder name')
        self._folder(name).mkdir(parents=True, exist_ok=True)
        return name

    def rename_folder(self, old, new):
        if old in (DEFAULT_FOLDER, TRASH_FOLDER) or new.strip() in (DEFAULT_FOLDER, TRASH_FOLDER):
            raise ValueError('That folder cannot be renamed')
        target = self._folder(new.strip())
        if target.exists():
            raise ValueError('A folder with that name exists')
        self._folder(old).rename(target)
        return new.strip()

    def delete_folder(self, name):
        """Notes of a deleted folder move to Recently Deleted; nothing is erased."""
        if name in (DEFAULT_FOLDER, TRASH_FOLDER):
            raise ValueError('That folder cannot be deleted')
        folder = self._folder(name)
        for note in self.notes(name):
            self.trash(name, note.ident)
        for leftover in folder.iterdir():  # unknown files stay put; refuse rather than lose them
            raise ValueError('Folder contains files that are not notes: ' + leftover.name)
        folder.rmdir()

    def notes(self, folder, query=''):
        out = []
        for p in self._folder(folder).glob('*.txt'):
            if not NOTE_RE.match(p.name):
                continue
            try:
                text = p.read_text(encoding='utf-8', errors='replace')
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if query and query.casefold() not in text.casefold():
                continue
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            out.append(Note(folder, p.name, title_of(text), mtime, lines[1][:80] if len(lines) > 1 else ''))
        return sorted(out, key=lambda n: -n.mtime)

    def search(self, query):
        return [n for f in self.folders() for n in self.notes(f, query)]

    def new_note(self, folder=DEFAULT_FOLDER, text=''):
        self.create_folder(folder) if not self._folder(folder).exists() else None
        while True:
            ident = time.strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(2) + '.txt'
            if not (self._folder(folder) / ident).exists():
                break
        atomic_write(self._file(folder, ident), text, 0o600)
        return ident

    def read(self, folder, ident):
        return self._file(folder, ident).read_text(encoding='utf-8', errors='replace')

    def write(self, folder, ident, text):
        atomic_write(self._file(folder, ident), text, 0o600)

    def move(self, folder, ident, target):
        src = self._file(folder, ident)
        self._folder(target).mkdir(parents=True, exist_ok=True)
        src.replace(self._file(target, ident))

    def trash(self, folder, ident):
        if folder != TRASH_FOLDER:
            self.move(folder, ident, TRASH_FOLDER)

    def restore(self, ident):
        self.move(TRASH_FOLDER, ident, DEFAULT_FOLDER)

    def import_legacy(self, path):
        """The first Notes build kept one file; adopt it once as a note."""
        path = Path(path)
        if path.exists() and path.stat().st_size:
            text = path.read_text(encoding='utf-8', errors='replace')
            path.rename(path.with_name(path.name + '.imported'))
            return self.new_note(DEFAULT_FOLDER, text)
        return None


MENU = [('File', [('New Note', 'new_note', '<Primary>n'), ('New Folder…', 'new_folder', '<Primary><Shift>n'), None, ('Move to Recently Deleted', 'trash', '<Primary>BackSpace'), ('Close', 'close', '<Primary>w')]),
        ('Edit', [('Undo', 'undo', '<Primary>z'), ('Redo', 'redo', '<Primary><Shift>z'), None, ('Find Notes', 'find', '<Primary>f')])]


class Notes:
    def __init__(self, app, store=None):
        self.store = store or NotesStore()
        legacy = common.STATE / 'notes.txt'
        try:
            self.store.import_legacy(legacy)
        except OSError:
            pass
        self.folder, self.ident, self.pending, self.loading, self.note_folder = DEFAULT_FOLDER, None, 0, False, DEFAULT_FOLDER
        self.aw = AppWindow(app, 'Notes', 900, 580, MENU)
        self.win = self.aw.win
        for name, fn in (('new_note', self.new_note), ('new_folder', self.new_folder), ('trash', self.trash_current), ('close', self.win.close),
                         ('undo', lambda: self.buffer.undo()), ('redo', lambda: self.buffer.redo()), ('find', lambda: self.search.grab_focus())):
            self.aw.action(name, fn)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=170, vexpand=True)
        self.folder_list = Gtk.ListBox(css_classes=['app-sidebar'])
        self.folder_list.connect('row-selected', self.pick_folder)
        left = ui.box(True)
        left.append(ui.scroll(self.folder_list))
        left.append(ui.button('New Folder', self.new_folder))
        inner = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=240)
        mid = ui.box(True, 4)
        self.search = Gtk.SearchEntry(placeholder_text='Search notes')
        self.search.connect('search-changed', lambda *_: self.fill_notes())
        self.note_list = Gtk.ListBox()
        self.note_list.connect('row-selected', self.pick_note)
        mid.append(self.search)
        mid.append(ui.scroll(self.note_list))
        self.buffer = Gtk.TextBuffer(enable_undo=True)
        self.view = Gtk.TextView(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=14, right_margin=14, top_margin=12, bottom_margin=12)
        self.buffer.connect('changed', self.edited)
        inner.set_start_child(mid)
        inner.set_end_child(ui.scroll(self.view))
        paned.set_start_child(left)
        paned.set_end_child(inner)
        paned.set_shrink_start_child(False)
        self.aw.body.append(paned)
        self.win.connect('close-request', lambda *_: (self.flush(), False)[1])
        self.fill_folders()

    # ---- lists
    def fill_folders(self, select=None):
        ui.clear(self.folder_list)
        select = select or self.folder
        for name in self.store.folders():
            row = Gtk.ListBoxRow()
            row.name = name
            row.set_child(Gtk.Label(label=name, xalign=0))
            self.folder_list.append(row)
            if name == select:
                self.folder_list.select_row(row)

    def pick_folder(self, _box, row):
        if row is None:
            return
        self.flush()
        self.folder = row.name
        self.fill_notes()

    def fill_notes(self, select=None):
        self.flush()
        ui.clear(self.note_list)
        query = self.search.get_text()
        notes = self.store.search(query) if query else self.store.notes(self.folder)
        target = None
        for note in notes:
            row = Gtk.ListBoxRow()
            row.note = note
            col = ui.box(True, 1)
            col.append(Gtk.Label(label=note.title, xalign=0, ellipsize=3, css_classes=['title-label']))
            col.append(Gtk.Label(label=time.strftime('%b %d  ', time.localtime(note.mtime)) + note.preview, xalign=0, ellipsize=3, css_classes=['hint']))
            row.set_child(col)
            self.note_list.append(row)
            if note.ident == select or (target is None and select is None):
                target = row
        if target:
            self.note_list.select_row(target)
        else:
            self.show(None, None)
        self.aw.say(f'{len(notes)} notes')

    def pick_note(self, _box, row):
        self.flush()
        self.show(row.note.folder, row.note.ident) if row else self.show(None, None)

    def show(self, folder, ident):
        self.loading = True
        self.ident = ident
        self.note_folder = folder
        self.buffer.set_text(self.store.read(folder, ident) if ident else '')
        self.view.set_editable(bool(ident))
        self.loading = False

    # ---- editing
    def edited(self, *_):
        if self.loading or not self.ident:
            return
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(600, self.flush)

    def flush(self):
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0
        if self.ident and not self.loading:
            text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)
            try:
                if text != self.store.read(self.note_folder, self.ident):
                    self.store.write(self.note_folder, self.ident, text)
            except (OSError, ValueError):
                pass
        return False

    def new_note(self):
        self.flush()
        folder = self.folder if self.folder != TRASH_FOLDER else DEFAULT_FOLDER
        ident = self.store.new_note(folder)
        self.search.set_text('')
        self.folder = folder
        self.fill_folders(folder)
        self.fill_notes(ident)
        self.view.grab_focus()
        return ident

    def new_folder(self):
        dialog = Gtk.Window(title='New Folder', transient_for=self.win, modal=True, default_width=320)
        col = ui.box(True, 10, 'sheet')
        entry = Gtk.Entry(placeholder_text='Folder name')
        err = Gtk.Label(label='', css_classes=['error-text'])

        def make(*_):
            try:
                name = self.store.create_folder(entry.get_text())
            except (ValueError, OSError):
                err.set_text('Choose a different name.')
                return
            dialog.destroy()
            self.fill_folders(name)
        entry.connect('activate', make)
        for w in (entry, err, ui.button('Create', make, 'suggested-action')):
            col.append(w)
        dialog.set_child(col)
        dialog.present()

    def trash_current(self):
        if self.ident:
            self.flush()
            if self.note_folder == TRASH_FOLDER:
                return
            self.store.trash(self.note_folder, self.ident)
            self.fill_folders(self.folder)
            self.fill_notes()


def open_window(app, path=None):
    n = Notes(app)
    n.aw.present()
    return n
