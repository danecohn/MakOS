"""Files: original GTK4 browser, list/icon/column views, tabs and safe GIO opening."""
import mimetypes
from pathlib import Path
from gi.repository import Gtk, Gio, Gdk, GLib
from . import ui


def entries(path):
    try:
        return sorted((p for p in Path(path).iterdir() if not p.name.startswith('.')), key=lambda p: (not p.is_dir(), p.name.casefold()))[:2000]
    except OSError:
        return []


def kind(path):
    if path.is_dir():
        return 'folder'
    mime = mimetypes.guess_type(path.name)[0] or ''
    return {'text': 'file-text', 'image': 'file-image', 'audio': 'file-audio', 'video': 'file-video'}.get(mime.split('/')[0], 'file-pdf' if mime == 'application/pdf' else 'file-generic')


def open_uri(path):
    context = Gio.AppLaunchContext()
    context.unsetenv('LD_PRELOAD')
    Gio.AppInfo.launch_default_for_uri(Path(path).absolute().as_uri(), context)


def preview(app, path):
    path = Path(path)
    w = ui.window(app, path.name, 740, 560)
    mime = mimetypes.guess_type(path.name)[0] or ''
    if mime.startswith('image/'):
        picture = Gtk.Picture.new_for_filename(str(path))
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        w.set_child(picture)
    elif mime.startswith('text/') or path.suffix in ('.py', '.md', '.json', '.log', '.css', '.js'):
        try:
            with path.open('r', errors='replace') as stream:
                content = stream.read(250000)
        except OSError as error:
            content = str(error)
        text = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text.get_buffer().set_text(content)
        w.set_child(ui.scroll(text))
    elif mime.startswith(('audio/', 'video/')):
        media = Gtk.Video.new_for_filename(str(path))
        w.set_child(media)
    else:
        col = ui.box(True, 18, 'sheet')
        col.append(ui.icon(kind(path), 96))
        col.append(Gtk.Label(label=path.name, selectable=True))
        col.append(ui.button('Open in default application', lambda: open_uri(path), 'suggested-action'))
        w.set_child(col)
    w.present()
    return w


class Files:
    def __init__(self, app, path=None):
        self.app = app
        self.path = Path(path or Path.home()).absolute()
        self.selected = None
        self.mode = 'icons'
        self.win = ui.window(app, 'Files', 960, 620)
        outer = ui.box(True)
        toolbar = ui.box(spacing=5, css='metal-toolbar')
        toolbar.append(ui.button('‹', self.up))
        toolbar.append(ui.button('New Tab', self.new_tab))
        for label, mode in [('Icons', 'icons'), ('List', 'list'), ('Columns', 'columns')]:
            toolbar.append(ui.button(label, lambda m=mode: self.view(m)))
        toolbar.append(ui.button('Preview', self.quicklook))
        actions=Gtk.MenuButton(label='Actions')
        pop=Gtk.Popover()
        actions_col=ui.box(True,3)
        for name,fn in [('Get Info',self.info),('New Folder',self.new_folder),('Rename',self.rename),('Move to Trash',self.trash)]:
            actions_col.append(ui.button(name,lambda fn=fn:(pop.popdown(),fn())))
        pop.set_child(actions_col)
        actions.set_popover(pop)
        toolbar.append(actions)
        self.location = Gtk.Entry(hexpand=True)
        self.location.connect('activate', lambda e: self.go(Path(e.get_text()).expanduser()))
        toolbar.append(self.location)
        outer.append(toolbar)
        split = ui.box()
        sidebar = ui.box(True, 2, 'source-list')
        sidebar.set_size_request(174, -1)
        sidebar.append(Gtk.Label(label='PLACES', xalign=0, css_classes=['source-heading']))
        for label, loc in [('Home', Path.home()), ('Desktop', Path.home() / 'Desktop'), ('Documents', Path.home() / 'Documents'),
                           ('Downloads', Path.home() / 'Downloads'), ('Pictures', Path.home() / 'Pictures'), ('Music', Path.home() / 'Music')]:
            sidebar.append(ui.button(label, lambda p=loc: self.go(p)))
        sidebar.append(Gtk.Label(label='DEVICES', xalign=0, css_classes=['source-heading']))
        sidebar.append(ui.button('Computer', lambda: self.go(Path('/'))))
        monitor = Gio.VolumeMonitor.get()
        for mount in monitor.get_mounts():
            p = mount.get_root().get_path()
            if p:
                sidebar.append(ui.button(mount.get_name(), lambda p=p: self.go(Path(p))))
        split.append(sidebar)
        self.tabs = Gtk.Notebook(hexpand=True, vexpand=True, scrollable=True)
        split.append(self.tabs)
        outer.append(split)
        self.status = Gtk.Label(xalign=0, css_classes=['statusbar'])
        outer.append(self.status)
        self.win.set_child(outer)
        self.new_tab()
        self.tabs.connect('switch-page',self.switched_tab)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.key)
        self.win.add_controller(keys)
        self.win.present()

    def switched_tab(self,_notebook,page,_index):
        self.path=page._path
        self.location.set_text(str(self.path))
        self.selected=None
        self.status.set_text(str(self.path))

    def new_tab(self):
        page = ui.box(True)
        page._path = self.path
        self.tabs.append_page(page, Gtk.Label(label=self.path.name or '/'))
        self.tabs.set_current_page(self.tabs.page_num(page))
        self.refresh()

    def key(self, _controller, key, _code, state):
        if key == Gdk.KEY_space and self.selected:
            self.quicklook()
            return True
        if key == Gdk.KEY_t and state & Gdk.ModifierType.CONTROL_MASK:
            self.new_tab()
            return True
        return False

    def up(self):
        self.go(self.path.parent)

    def view(self, mode):
        self.mode = mode
        self.refresh()

    def go(self, path):
        if not path.is_dir():
            ui.message(self.app, 'Files', 'This folder is unavailable.')
            return
        self.path = path.absolute()
        self.refresh()

    def quicklook(self):
        if self.selected:
            preview(self.app, self.selected)

    def pick(self, path):
        self.selected = path
        self.status.set_text(str(path))

    def activate(self, path):
        if path.is_dir():
            self.go(path)
        else:
            try:
                open_uri(path)
            except Exception as error:
                ui.message(self.app, 'Cannot open file', str(error))

    def refresh(self):
        self.selected = None
        self.location.set_text(str(self.path))
        page = self.tabs.get_nth_page(self.tabs.get_current_page())
        page._path = self.path
        ui.clear(page)
        self.tabs.set_tab_label_text(page, self.path.name or '/')
        paths = entries(self.path)
        if self.mode == 'columns':
            columns = ui.box()
            root=Path.home() if self.path.is_relative_to(Path.home()) else Path('/')
            chain=[root]
            for component in self.path.relative_to(root).parts:
                chain.append(chain[-1]/component)
            for directory in chain:
                listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
                for p in entries(directory):
                    row = Gtk.ListBoxRow()
                    row._path = p
                    row.set_child(Gtk.Label(label=p.name + ('  ›' if p.is_dir() else ''), xalign=0, margin_start=10, margin_end=10, margin_top=6, margin_bottom=6))
                    listing.append(row)
                listing.connect('row-selected', lambda _l, r: self.pick(r._path) if r else None)
                listing.connect('row-activated', lambda _l, r: self.activate(r._path))
                columns.append(ui.scroll(listing, 250))
            page.append(columns)
        elif self.mode == 'list':
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            for p in paths:
                row = Gtk.ListBoxRow()
                row._path = p
                line = ui.box(spacing=12)
                line.append(ui.icon(kind(p), 24))
                line.append(Gtk.Label(label=p.name, xalign=0, hexpand=True, margin_top=6, margin_bottom=6))
                try:
                    size = 'Folder' if p.is_dir() else f'{p.stat().st_size:,} bytes'
                except OSError:
                    size = 'Unavailable'
                line.append(Gtk.Label(label=size, margin_end=15, css_classes=['subtitle']))
                row.set_child(line)
                listing.append(row)
            listing.connect('row-selected', lambda _l, r: self.pick(r._path) if r else None)
            listing.connect('row-activated', lambda _l, r: self.activate(r._path))
            page.append(ui.scroll(listing))
        else:
            flow = Gtk.FlowBox(valign=Gtk.Align.START, selection_mode=Gtk.SelectionMode.SINGLE,
                               max_children_per_line=10, min_children_per_line=3, row_spacing=8, column_spacing=4)
            for p in paths:
                tile = ui.box(True, 7, 'file-tile')
                tile.set_size_request(116, 105)
                tile.append(ui.icon(kind(p), 56))
                tile.append(Gtk.Label(label=p.name, wrap=True, max_width_chars=16, lines=2))
                child = Gtk.FlowBoxChild()
                child._path = p
                child.set_child(tile)
                flow.append(child)
            flow.connect('selected-children-changed', lambda f: self.pick(f.get_selected_children()[0]._path) if f.get_selected_children() else None)
            flow.connect('child-activated', lambda _f, c: self.activate(c._path))
            page.append(ui.scroll(flow))
        self.status.set_text(f'{len(paths)} items  ·  {self.path}')

    def info(self):
        path=self.selected or self.path
        try:
            st=path.stat()
            import datetime
            details=f"{path}\n\nSize: {st.st_size:,} bytes\nModified: {datetime.datetime.fromtimestamp(st.st_mtime).isoformat(sep=' ',timespec='seconds')}\nPermissions: {oct(st.st_mode & 0o777)}\nType: {'Folder' if path.is_dir() else mimetypes.guess_type(path.name)[0] or 'File'}"
        except OSError as error:
            details=str(error)
        ui.message(self.app,'Get Info',details)

    def name_sheet(self,title,initial,action):
        w=ui.window(self.app,title,420,190)
        w.set_transient_for(self.win)
        w.set_modal(True)
        col=ui.box(True,14,'sheet')
        entry=Gtk.Entry(text=initial)
        error=Gtk.Label(xalign=0,wrap=True)
        col.append(entry)
        col.append(error)
        def apply():
            name=entry.get_text().strip()
            if not name or name in ('.','..') or '/' in name or '\0' in name:
                error.set_text('Choose a name without path separators.')
                return
            try:
                action(name)
            except OSError as exc:
                error.set_text(str(exc))
                return
            w.close()
            self.refresh()
        row=ui.box(spacing=12)
        row.append(ui.button('Cancel',w.close))
        row.append(ui.button('Save',apply,'suggested-action'))
        col.append(row)
        entry.connect('activate',lambda *_:apply())
        w.set_child(col)
        w.present()

    def new_folder(self):
        self.name_sheet('New Folder','Untitled Folder',lambda name:(self.path/name).mkdir())

    def rename(self):
        if not self.selected:return
        source=self.selected
        def move(name):
            target=source.with_name(name)
            if target.exists():
                raise FileExistsError('An item with that name already exists.')
            # GIO move without overwrite flags protects existing targets from races.
            Gio.File.new_for_path(str(source)).move(Gio.File.new_for_path(str(target)),Gio.FileCopyFlags.NONE,None,None,None)
        def run(name):
            try:move(name)
            except GLib.Error as error:raise OSError(error.message) from None
        self.name_sheet('Rename',source.name,run)

    def trash(self):
        if not self.selected:return
        source=self.selected
        w=ui.window(self.app,'Move to Trash',440,190)
        w.set_transient_for(self.win);w.set_modal(True)
        col=ui.box(True,16,'sheet')
        col.append(Gtk.Label(label=f'Move {source.name} to Trash?',wrap=True))
        row=ui.box(spacing=12)
        row.append(ui.button('Cancel',w.close))
        def move():
            try:
                Gio.File.new_for_path(str(source)).trash(None)
            except GLib.Error as error:
                ui.message(self.app,'Cannot move to Trash',error.message)
            w.close();self.refresh()
        row.append(ui.button('Move to Trash',move,'suggested-action'))
        col.append(row);w.set_child(col);w.present()
