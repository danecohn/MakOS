"""Get Info panel: general, tags, comments, open-with, permissions. Folder sizes are computed off the main thread."""
import os
import stat
import threading
import time

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk, Pango

from .. import ui
from . import content, model, panes, tags, widgets


def _kv(grid, row, key, value, selectable=True):
    a = Gtk.Label(label=key, xalign=1, yalign=0, css_classes=['subtitle'])
    b = Gtk.Label(label=value, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=44, selectable=selectable)
    grid.attach(a, 0, row, 1, 1)
    grid.attach(b, 1, row, 1, 1)
    return b


def _heading(text):
    return Gtk.Label(label=text.upper(), xalign=0, css_classes=['source-heading', 'info-heading'])


class GetInfo:
    def __init__(self, files, entries):
        self.files = files
        self.entries = [e for e in entries if e is not None]
        self.cancel = threading.Event()
        many = len(self.entries) > 1
        title = f'{len(self.entries)} Items Info' if many else f'{self.entries[0].name} Info'
        w = ui.window(files.app, title, 420, 640)
        w.set_transient_for(files.win)
        w.add_css_class('getinfo')
        w.connect('close-request', lambda *_: (self.cancel.set(), False)[1])
        self.win = w
        col = ui.box(True, 8, 'info-body')
        col.set_margin_start(16)
        col.set_margin_end(16)
        col.set_margin_top(12)
        col.set_margin_bottom(12)
        head = ui.box(spacing=14)
        e0 = self.entries[0]
        head.append(widgets.make_icon('file-generic' if many else e0.icon, 64))
        t = ui.box(True, 3)
        self.name_label = Gtk.Label(label=f'{len(self.entries)} items' if many else e0.name, xalign=0, wrap=True,
                                    max_width_chars=32, css_classes=['sheet-title'], selectable=True)
        self.size_label = Gtk.Label(label='', xalign=0, css_classes=['subtitle'])
        t.append(self.name_label)
        t.append(self.size_label)
        head.append(t)
        col.append(head)
        self.grid = Gtk.Grid(column_spacing=12, row_spacing=4, margin_top=6)
        col.append(self.grid)
        self._general()
        col.append(_heading('Tags'))
        col.append(self._tags())
        if not many:
            col.append(_heading('Comments'))
            col.append(self._comments())
            if not e0.is_dir and e0.path:
                col.append(_heading('Open with'))
                col.append(self._open_with())
            if e0.path:
                col.append(_heading('Sharing & Permissions'))
                col.append(self._permissions())
        w.set_child(ui.scroll(col))
        w.present()

    # -- general
    def _general(self):
        es = self.entries
        row = 0
        if len(es) == 1:
            e = es[0]
            kind = e.kind
            if e.mime and not e.is_dir:
                kind = f'{e.kind} ({e.mime})'
            _kv(self.grid, row, 'Kind', kind)
            row += 1
            self.size_value = _kv(self.grid, row, 'Size', '--' if e.is_dir else f'{model.human_size(e.size)} ({e.size:,} bytes)')
            row += 1
            _kv(self.grid, row, 'Where', e.where or os.path.dirname(e.path) or e.uri)
            row += 1
            if e.is_symlink:
                _kv(self.grid, row, 'Alias to', e.link_target or 'a missing item')
                row += 1
            try:
                st = os.lstat(e.path) if e.path else None
            except OSError:
                st = None
            if st is not None:
                if getattr(st, 'st_birthtime', 0):
                    _kv(self.grid, row, 'Created', time.strftime('%A %d %B %Y, %H:%M', time.localtime(st.st_birthtime)))
                    row += 1
                _kv(self.grid, row, 'Modified', time.strftime('%A %d %B %Y, %H:%M', time.localtime(st.st_mtime)))
                row += 1
                _kv(self.grid, row, 'Last opened', time.strftime('%A %d %B %Y, %H:%M', time.localtime(st.st_atime)))
                row += 1
            for k, v in (content.metadata_rows(e.path)[4:] if e.path and not e.is_dir else []):
                if k not in ('Modified', 'Created', 'Alias to', 'Where'):
                    _kv(self.grid, row, k, str(v))
                    row += 1
            self.size_label.set_text(model.human_size(e.size) if not e.is_dir else 'Calculating size…')
        else:
            kinds = {e.kind for e in es}
            _kv(self.grid, row, 'Kind', next(iter(kinds)) if len(kinds) == 1 else 'Multiple kinds')
            row += 1
            self.size_value = _kv(self.grid, row, 'Size', 'Calculating…')
            self.size_label.set_text('Calculating size…')
        self._measure()

    def _measure(self):
        dirs = [e for e in self.entries if e.is_dir and e.path and not e.is_symlink]
        loose = sum(e.size for e in self.entries if not e.is_dir)
        if not dirs:
            if len(self.entries) > 1:
                self.size_value.set_text(model.human_size(loose))
                self.size_label.set_text(model.human_size(loose))
            return

        def work():
            total, files, folders, complete = loose, 0, 0, True
            for d in dirs:
                t, f, fo, c = model.folder_size(d.path, self.cancel)
                total += t
                files += f
                folders += fo
                complete = complete and c
                if self.cancel.is_set():
                    return
            GLib.idle_add(done, total, files, folders, complete)

        def done(total, files, folders, complete):
            text = model.human_size(total) + ('' if complete else ' or more (some items could not be read)')
            detail = f'{text}  ({files} files, {folders} folders)'
            self.size_value.set_text(detail)
            self.size_label.set_text(text)
            return False
        threading.Thread(target=work, daemon=True, name='makos-info-size').start()

    # -- tags
    def _tags(self):
        box = ui.box(True, 6)
        row = ui.box(spacing=6)
        paths = [e.path for e in self.entries if e.path]
        self.tag_buttons = {}

        def toggle(name):
            if not paths:
                return
            tags.STORE.toggle_tag(paths, name)
            self.files.refresh_entries(self.entries)
            sync()

        def sync():
            have = {}
            for p in paths:
                for t in tags.STORE.get_tags(p):
                    have[t.casefold()] = have.get(t.casefold(), 0) + 1
            for name, b in self.tag_buttons.items():
                n = have.get(name.casefold(), 0)
                b.set_active(n == len(paths) and n > 0)
                b.set_opacity(1.0 if n else .6)
        for name in tags.COLOURS:
            b = Gtk.ToggleButton()
            b.add_css_class('tag-toggle')
            b.add_css_class('tagdot-' + name.casefold())
            b.set_child(Gtk.Label(label='●'))
            b.set_tooltip_text(name)
            b.connect('clicked', lambda btn, n=name: toggle(n) if btn.get_active() != (self._have(n, paths)) else None)
            self.tag_buttons[name] = b
            row.append(b)
        box.append(row)
        add = ui.box(spacing=6)
        entry = Gtk.Entry(placeholder_text='Add a tag…', hexpand=True)

        def add_custom(*_):
            name = entry.get_text().strip()
            if name and paths:
                for p in paths:
                    tags.STORE.add_tag(p, name)
                entry.set_text('')
                self.files.refresh_entries(self.entries)
                self.files.refresh_sidebar()
                show_extra()
        entry.connect('activate', add_custom)
        add.append(entry)
        add.append(ui.button('Add', add_custom))
        box.append(add)
        extra = Gtk.Label(xalign=0, wrap=True, css_classes=['subtitle'])
        box.append(extra)

        def show_extra():
            names = []
            for p in paths:
                names += [t for t in tags.STORE.get_tags(p) if t.title() not in tags.COLOURS]
            extra.set_text('Other tags: ' + ', '.join(dict.fromkeys(names)) if names else '')
        sync()
        show_extra()
        if not paths:
            box.set_sensitive(False)
        return box

    @staticmethod
    def _have(name, paths):
        return bool(paths) and all(any(t.casefold() == name.casefold() for t in tags.STORE.get_tags(p)) for p in paths)

    # -- comments
    def _comments(self):
        e = self.entries[0]
        box = ui.box(True, 4)
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6, left_margin=8, right_margin=8)
        view.set_size_request(-1, 70)
        if e.path:
            view.get_buffer().set_text(tags.STORE.get_comment(e.path))
        box.append(ui.scroll(view, None, 70))
        status = Gtk.Label(xalign=0, css_classes=['subtitle'])

        def save():
            if not e.path:
                return
            buf = view.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
            try:
                tags.STORE.set_comment(e.path, text)
                status.set_text('Comment saved.')
            except OSError as exc:
                status.set_text(model.human_error(exc, e.name))
        row = ui.box(spacing=8)
        row.append(ui.button('Save Comment', save))
        row.append(status)
        box.append(row)
        if not e.path:
            box.set_sensitive(False)
        return box

    # -- open with
    def _open_with(self):
        e = self.entries[0]
        box = ui.box(spacing=8)
        apps = Gio.AppInfo.get_all_for_type(e.mime) if e.mime else []
        default = Gio.AppInfo.get_default_for_type(e.mime, False) if e.mime else None
        names = [a.get_display_name() for a in apps]
        if not apps:
            box.append(Gtk.Label(label='No application is registered for this kind of file.', xalign=0, css_classes=['subtitle']))
            return box
        drop = Gtk.DropDown.new_from_strings(names)
        if default is not None:
            for i, a in enumerate(apps):
                if a.get_id() == default.get_id():
                    drop.set_selected(i)
        drop.set_hexpand(True)
        box.append(drop)
        status = Gtk.Label(css_classes=['subtitle'])

        def change_all():
            app = apps[drop.get_selected()]
            try:
                app.set_as_default_for_type(e.mime)
                status.set_text(f'All “{e.kind}” files now open with {app.get_display_name()}.')
            except GLib.Error as err:
                status.set_text(err.message)
        box.append(ui.button('Change All…', change_all))
        wrap = ui.box(True, 4)
        wrap.append(box)
        wrap.append(status)
        return wrap

    # -- permissions
    def _permissions(self):
        e = self.entries[0]
        box = ui.box(True, 6)
        try:
            st = os.lstat(e.path)
        except OSError as exc:
            box.append(Gtk.Label(label=model.human_error(exc, e.name), xalign=0))
            return box
        owner, group = content.owner_name(st.st_uid), content.group_name(st.st_gid)
        box.append(Gtk.Label(label=f'Owner: {owner}    Group: {group}    Mode: {stat.filemode(st.st_mode)}', xalign=0, selectable=True))
        grid = Gtk.Grid(column_spacing=14, row_spacing=3)
        for j, h in enumerate(('Read', 'Write', 'Execute' if not e.is_dir else 'Open')):
            grid.attach(Gtk.Label(label=h, css_classes=['subtitle']), j + 1, 0, 1, 1)
        checks = {}
        for i, (who, shift) in enumerate((('Owner', 6), ('Group', 3), ('Others', 0))):
            grid.attach(Gtk.Label(label=who, xalign=1), 0, i + 1, 1, 1)
            for j, bit in enumerate((4, 2, 1)):
                c = Gtk.CheckButton(active=bool(st.st_mode >> shift & bit))
                checks[(shift, bit)] = c
                grid.attach(c, j + 1, i + 1, 1, 1)
        box.append(grid)
        status = Gtk.Label(xalign=0, wrap=True, css_classes=['subtitle'])

        def apply():
            mode = stat.S_IMODE(st.st_mode) & ~0o777
            for (shift, bit), c in checks.items():
                if c.get_active():
                    mode |= bit << shift
            try:
                os.chmod(e.path, mode)
                status.set_text('Permissions changed.')
                self.files.refresh_entries([e])
            except OSError as exc:
                status.set_text(model.human_error(exc, e.name))
        apply_btn = ui.button('Apply Permissions', apply)
        box.append(apply_btn)
        box.append(status)
        if st.st_uid != os.getuid() or e.is_symlink:
            grid.set_sensitive(False)
            apply_btn.set_sensitive(False)
            status.set_text('Only the owner can change permissions of a real file.' if st.st_uid != os.getuid() else
                            'Aliases have no permissions of their own; get info on the original.')
        return box
