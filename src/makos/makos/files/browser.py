"""The Files window: toolbar, path bar, sidebar, tabs, actions, clipboard, operations and shortcuts."""
import os
import shutil
import threading
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from .. import ui
from . import archive, config, content, dnd, getinfo, model, network, ops, quicklook, shortcuts, sheets, tags, trash as trashlib
from .location import Loc
from .sidebar import Sidebar
from .tab import Tab, idle
from .widgets import popup_menu

BLOCKED_TYPES = ('application/x-executable', 'application/x-pie-executable', 'application/x-sharedlib',
                 'application/vnd.appimage', 'application/x-ms-dos-executable', 'application/x-msdownload',
                 'application/x-mach-binary', 'application/x-elf')
VIEW_LABELS = [('icons', 'Icons'), ('list', 'List'), ('columns', 'Columns'), ('cover', 'Cover')]


def launch_context():
    ctx = Gio.AppLaunchContext()
    ctx.unsetenv('LD_PRELOAD')
    return ctx


class OpenRefused(Exception):
    pass


def check_openable(mime, path=''):
    """MakOS never runs programs from Files: binaries and AppImages are refused, everything else uses the default app."""
    if mime in BLOCKED_TYPES:
        raise OpenRefused('Files does not run programs. To start an application use the launcher, or a terminal.')


class PathBar(Gtk.Stack):
    def __init__(self, files):
        super().__init__(hexpand=True, transition_type=Gtk.StackTransitionType.NONE)
        self.files = files
        self.crumbs = ui.box(spacing=0)
        self.crumbs.add_css_class('crumbs')
        sc = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True)
        sc.set_child(self.crumbs)
        sc.set_propagate_natural_height(True)
        self.scroller = sc
        self.add_named(sc, 'crumbs')
        self.entry = Gtk.Entry(hexpand=True)
        self.entry.add_css_class('path-entry')
        self.add_named(self.entry, 'entry')
        self.entry.connect('activate', self._go)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', lambda _c, k, *_: (self.close_entry(), True)[1] if k == Gdk.KEY_Escape else False)
        self.entry.add_controller(keys)
        click = Gtk.GestureClick(button=1)
        click.connect('pressed', lambda g, n, x, y: self.edit() if n == 2 else None)
        sc.add_controller(click)

    def set_location(self, loc):
        child = self.crumbs.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.crumbs.remove(child)
            child = nxt
        crumbs = loc.breadcrumbs()
        for i, (label, target) in enumerate(crumbs):
            b = Gtk.Button(label=label)
            b.add_css_class('crumb')
            if i == len(crumbs) - 1:
                b.add_css_class('crumb-current')
            b.connect('clicked', lambda _b, t=target: self.files.open_location(t))
            self.crumbs.append(b)
            if i < len(crumbs) - 1:
                self.crumbs.append(Gtk.Label(label='›', css_classes=['crumb-sep']))
        adj = self.scroller.get_hadjustment()
        GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])
        if loc.kind == 'dir':
            self.entry.set_text(loc.path)
        elif loc.kind == 'remote':
            self.entry.set_text(loc.uri)
        else:
            self.entry.set_text('')

    def edit(self):
        self.set_visible_child_name('entry')
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def close_entry(self):
        self.set_visible_child_name('crumbs')
        self.files.focus_view()

    def _go(self, *_):
        text = self.entry.get_text().strip()
        self.files.open_text_location(text)
        self.close_entry()


class Files:
    def __init__(self, app, path=None):
        self.app = app
        self.prefs = config.load()
        self.tabs_list = []
        self.current = None
        self.clip = None                     # ('copy'|'cut', [locations]) the last thing this window put on the clipboard
        self.search_contents = False
        self.search_scope = 'folder'
        self._search_timer = 0
        self._status_text = ''
        self.win = ui.window(app, 'Files', self.prefs['width'], self.prefs['height'])
        self.win.add_css_class('files-window')
        self._load_css()
        self.engine = ops.Engine(dispatch=idle, ask=sheets.ask_conflict(self))
        self.engine.on_job_added = lambda job: sheets.ProgressSheet(self, job)
        self.engine.on_job_done = self._job_done
        self.engine.on_history = self.sync_toolbar
        self.quicklook = quicklook.QuickLook(app, self.win, step=self.step_selection, open_cb=lambda e: self.activate_entry(e, self.current, from_ql=True))
        self._build(path)
        self.win.present()

    # ------------------------------------------------------------ window
    def _load_css(self):
        display = Gdk.Display.get_default()
        if display is None or getattr(Files, '_css', None):
            return
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(str(Path(__file__).with_name('files.css')))
        except GLib.Error:
            return
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        Files._css = provider

    def _build(self, path):
        outer = ui.box(True)
        tb = ui.box(spacing=8, css='metal-toolbar')
        tb.add_css_class('files-toolbar')
        nav = ui.box(spacing=0)
        nav.add_css_class('linked')
        self.back_btn = Gtk.Button(label='‹', tooltip_text='Back (Alt+Left)')
        self.fwd_btn = Gtk.Button(label='›', tooltip_text='Forward (Alt+Right)')
        self.back_btn.connect('clicked', lambda *_: self.do_action('back'))
        self.fwd_btn.connect('clicked', lambda *_: self.do_action('forward'))
        nav.append(self.back_btn)
        nav.append(self.fwd_btn)
        tb.append(nav)
        seg = ui.box(spacing=0)
        seg.add_css_class('linked')
        seg.add_css_class('segmented')
        self.view_buttons = {}
        first = None
        for mode, label in VIEW_LABELS:
            b = Gtk.ToggleButton(label=label, tooltip_text=f'{label} view')
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect('toggled', lambda btn, m=mode: btn.get_active() and self.view(m))
            self.view_buttons[mode] = b
            seg.append(b)
        tb.append(seg)
        self.arrange_btn = Gtk.MenuButton(label='Arrange')
        self.arrange_pop = Gtk.Popover()
        self.arrange_btn.set_popover(self.arrange_pop)
        self.arrange_btn.set_create_popup_func(lambda *_: self._fill_pop(self.arrange_pop, self.arrange_rows()))
        tb.append(self.arrange_btn)
        self.action_btn = Gtk.MenuButton(label='Action')
        self.action_pop = Gtk.Popover()
        self.action_btn.set_popover(self.action_pop)
        self.action_btn.set_create_popup_func(lambda *_: self._fill_pop(self.action_pop, self.action_rows()))
        tb.append(self.action_btn)
        tb.append(ui.button('Quick Look', lambda: self.do_action('quicklook')))
        spacer = Gtk.Box(hexpand=True)
        tb.append(spacer)
        self.search = Gtk.SearchEntry(placeholder_text='Search', width_chars=22)
        self.search.connect('search-changed', self._search_changed)
        self.search.connect('stop-search', lambda *_: self.end_search())
        tb.append(self.search)
        outer.append(tb)
        row = ui.box(spacing=6, css='path-row')
        self.pathbar = PathBar(self)
        row.append(self.pathbar)
        outer.append(row)
        self.search_bar = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        sb = ui.box(spacing=8, css='path-row')
        sb.append(Gtk.Label(label='Search:', css_classes=['subtitle']))
        self.scope_buttons = {}
        first = None
        for key, label in (('folder', 'This Folder'), ('home', 'Home'), ('computer', 'Computer')):
            b = Gtk.ToggleButton(label=label)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.set_active(key == 'folder')
            b.connect('toggled', lambda btn, k=key: btn.get_active() and self._scope(k))
            self.scope_buttons[key] = b
            sb.append(b)
        self.contents_check = Gtk.CheckButton(label='File contents')
        self.contents_check.connect('toggled', lambda c: self._contents(c.get_active()))
        sb.append(self.contents_check)
        self.search_bar.set_child(sb)
        outer.append(self.search_bar)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=False, vexpand=True)
        self.sidebar = Sidebar(self)
        self.sidebar.set_size_request(150, -1)
        self.paned.set_start_child(self.sidebar)
        self.paned.set_resize_start_child(False)
        self.paned.set_shrink_start_child(False)
        self.paned.set_position(self.prefs['sidebar_width'])
        self.tabs = Gtk.Notebook(hexpand=True, vexpand=True, scrollable=True)
        self.tabs.add_css_class('files-tabs')
        newtab = Gtk.Button(label='+', has_frame=False, tooltip_text='New Tab (Ctrl+T)')
        newtab.connect('clicked', lambda *_: self.new_tab())
        self.tabs.set_action_widget(newtab, Gtk.PackType.END)
        newtab.set_visible(True)
        self.paned.set_end_child(self.tabs)
        self.paned.set_shrink_end_child(False)
        outer.append(self.paned)
        status = ui.box(spacing=10, css='statusbar')
        self.status = Gtk.Label(xalign=0, hexpand=True, ellipsize=3)
        status.append(self.status)
        self.zoom = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 32, 160, 8)
        self.zoom.set_value(self.prefs['icon_size'])
        self.zoom.set_size_request(130, -1)
        self.zoom.set_draw_value(False)
        self.zoom.set_tooltip_text('Icon size')
        self.zoom.connect('value-changed', self._zoom_changed)
        status.append(self.zoom)
        outer.append(status)
        self.win.set_child(outer)
        self.tabs.connect('switch-page', self._switched)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._key)
        self.win.add_controller(keys)
        self.win.connect('close-request', self._closing)
        self._wire_window_drop()
        start = Loc.dir(path) if path else Loc.dir(Path.home())
        if not os.path.isdir(start.path):
            start = Loc.dir(Path.home())
        self.new_tab(start)

    def _wire_window_drop(self):
        pass

    def _closing(self, *_):
        w, h = self.win.get_default_size()
        if w > 100 and h > 100:
            self.prefs['width'], self.prefs['height'] = w, h
        self.prefs['sidebar_width'] = self.paned.get_position()
        self.save_prefs()
        for t in list(self.tabs_list):
            t.close()
        self.quicklook.close()
        return False

    def save_prefs(self):
        config.save(self.prefs)

    # ------------------------------------------------------------ tabs & locations
    @property
    def path(self):
        t = self.current
        return Path(t.loc.path if t.loc.kind == 'dir' else t.last_local) if t else Path.home()

    def new_tab(self, loc=None):
        if loc is None:
            loc = self.current.loc if self.current is not None and self.current.loc.kind in ('dir', 'remote') else Loc.dir(Path.home())
        if isinstance(loc, (str, Path)):
            loc = Loc.dir(loc)
        tab = Tab(self, loc)
        self.tabs_list.append(tab)
        head = ui.box(spacing=4)
        head.append(tab.tab_label)
        close = Gtk.Button(label='×', has_frame=False, tooltip_text='Close Tab (Ctrl+W)')
        close.add_css_class('tab-close')
        close.connect('clicked', lambda *_: self.close_tab(tab))
        head.append(close)
        idx = self.tabs.append_page(tab.page, head)
        self.tabs.set_tab_reorderable(tab.page, True)
        self.current = tab
        self.tabs.set_current_page(idx)
        tab.page._tab = tab
        tab.build_view()
        tab.load()
        self._tab_bar_visibility()
        return tab

    def close_tab(self, tab):
        if len(self.tabs_list) <= 1:
            self.win.close()
            return
        idx = self.tabs.page_num(tab.page)
        tab.close()
        self.tabs_list.remove(tab)
        self.tabs.remove_page(idx)
        self._tab_bar_visibility()

    def _tab_bar_visibility(self):
        self.tabs.set_show_tabs(len(self.tabs_list) > 1)

    def _switched(self, _nb, page, _idx):
        tab = getattr(page, '_tab', None)
        if tab is None:
            return
        self.current = tab
        self.location_changed(tab)
        self.selection_changed()
        self.sync_toolbar()

    def go(self, path):
        path = Path(path)
        if not path.is_dir():
            sheets.message(self, 'Files', 'This folder is unavailable.')
            return
        self.open_location(Loc.dir(path))

    def open_location(self, loc, new_tab=False):
        if loc is None:
            return
        if new_tab:
            self.new_tab(loc)
            return
        if loc.kind == 'dir' and not os.path.isdir(loc.path):
            sheets.message(self, 'Files', f'“{loc.title}” is unavailable. It may have been moved, or its drive disconnected.')
            return
        self._end_search_ui()
        self.current.navigate(loc)
        self.focus_view()

    def open_text_location(self, text):
        if not text:
            return
        if '://' in text:
            try:
                uri = network.normalize_server(text)
            except network.ServerError as exc:
                sheets.message(self, 'Cannot open location', str(exc))
                return
            self.open_remote(uri)
            return
        p = Path(os.path.expandvars(text)).expanduser()
        if p.is_dir():
            self.open_location(Loc.dir(p))
        elif p.exists():
            self.open_location(Loc.dir(p.parent))
            self.current.reveal(str(p))
        else:
            sheets.message(self, 'Cannot open location', f'“{text}” does not exist.')

    def open_remote(self, uri):
        self.set_status('Connecting…')

        def done(ok, msg):
            if ok:
                self.open_location(Loc.remote(uri))
            else:
                self.set_status('')
                sheets.message(self, 'Cannot connect', msg or 'The connection failed.')
        network.mount_location(uri, self.win, done)

    def new_tab_here(self):
        self.new_tab()

    def focus_view(self):
        if self.current and self.current.view:
            self.current.view.focus()

    def view(self, mode):
        self.prefs['view'] = mode
        self.save_prefs()
        self.current.set_mode(mode)

    # ------------------------------------------------------------ state / feedback
    def set_status(self, text):
        self._status_text = text
        self.status.set_text(text)

    def location_changed(self, tab, columns=False):
        if tab is not self.current:
            return
        self.pathbar.set_location(tab.loc)
        self.win._title.set_text(tab.loc.title)
        self.win.set_title(tab.loc.title)
        self.sidebar.select(tab.loc)
        self.sync_toolbar()
        if tab.loc.kind != 'search':
            self.search.set_text('') if self.search.get_text() and not self._search_timer else None

    def listing_done(self, tab, count, seconds, searching=False):
        if tab is self.current:
            self.selection_changed()

    def listing_changed(self, tab):
        if tab is self.current:
            self.selection_changed()

    def selection_changed(self):
        tab = self.current
        if tab is None:
            return
        sel = tab.selected_entries()
        total = tab.store.get_n_items()
        if tab.view is not None and tab.view.mode == 'columns':
            col = tab.view.columns[-1] if tab.view.columns else None
            total = col.store.get_n_items() if col else 0
        if sel:
            size = sum(e.size for e in sel if not e.is_dir)
            text = f'{len(sel)} of {total:,} selected' + (f'  ·  {model.human_size(size)}' if size else '')
        else:
            text = f'{total:,} item' + ('' if total == 1 else 's')
            if tab.loc.kind == 'dir':
                try:
                    free = shutil.disk_usage(tab.loc.path).free
                    text += f',  {model.human_size(free)} available'
                except OSError:
                    pass
            if tab.loading:
                text = f'Loading… {total:,} items'
        self.set_status(text)
        if self.quicklook.visible() and len(sel) == 1:
            self.quicklook.show(sel[0])

    def sync_toolbar(self):
        tab = self.current
        if tab is None:
            return
        self.back_btn.set_sensitive(bool(tab.back))
        self.fwd_btn.set_sensitive(bool(tab.fwd))
        mode = tab.mode
        for m, b in self.view_buttons.items():
            if b.get_active() != (m == mode):
                b.set_active(m == mode)
        self.zoom.set_visible(tab.effective_mode() in ('icons', 'cover'))

    def _zoom_changed(self, scale):
        size = int(round(scale.get_value() / 8) * 8)
        if size != self.prefs['icon_size']:
            self.prefs['icon_size'] = size
            self.save_prefs()
            tab = self.current
            if tab and tab.view:
                tab.view.set_icon_size(size)

    # ------------------------------------------------------------ search
    def _search_changed(self, entry):
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(280, self._run_search_now)

    def _run_search_now(self):
        self._search_timer = 0
        text = self.search.get_text().strip()
        tab = self.current
        if not text:
            self.end_search()
            return False
        if tab.loc.kind != 'search':
            tab.search_origin = tab.loc
        root = self._search_root(tab)
        self.search_bar.set_reveal_child(True)
        tab.navigate(Loc('search', arg=text, root=root), push=False)
        return False

    def _search_root(self, tab):
        if self.search_scope == 'computer':
            return '/'
        if self.search_scope == 'home':
            return str(Path.home())
        origin = tab.search_origin if tab.search_origin is not None else tab.loc
        return origin.path if origin.kind == 'dir' else str(Path.home())

    def _scope(self, key):
        self.search_scope = key
        if self.search.get_text().strip():
            self._run_search_now()

    def _contents(self, on):
        self.search_contents = on
        if self.search.get_text().strip():
            self._run_search_now()

    def end_search(self):
        tab = self.current
        self.search.set_text('')
        self._end_search_ui()
        if tab is not None and tab.loc.kind == 'search':
            origin = tab.search_origin or Loc.dir(Path.home())
            tab.search_origin = None
            tab.navigate(origin, push=False)
        self.focus_view()

    def _end_search_ui(self):
        self.search_bar.set_reveal_child(False)

    def focus_search(self):
        self.search.grab_focus()

    # ------------------------------------------------------------ keyboard
    def _key(self, _c, keyval, _code, state):
        focus = self.win.get_focus()
        w = focus
        while w is not None:
            if isinstance(w, Gtk.Editable) or isinstance(w, Gtk.TextView):
                if keyval == Gdk.KEY_Escape and w is not None:
                    return False
                return False
            w = w.get_parent()
        if self.quicklook.visible() and self.quicklook.win.is_active():
            return False
        action = shortcuts.resolve(keyval, state)
        if action is None:
            return False
        return bool(self.do_action(action))

    def do_action(self, name):
        tab = self.current
        sel = tab.selected_entries() if tab else []
        handler = {
            'copy': lambda: self.copy_selection(False), 'cut': lambda: self.copy_selection(True), 'paste': self.paste,
            'select-all': lambda: tab.view.select_all(), 'undo': self.undo, 'redo': self.redo,
            'trash': self.trash_selection, 'delete': self.delete_selection, 'open': self.open_selection,
            'parent': self.go_parent, 'info': self.get_info, 'duplicate': self.duplicate_selection,
            'new-folder': self.new_folder, 'new-window': lambda: Files(self.app, self.path),
            'new-tab': self.new_tab, 'close-tab': lambda: self.close_tab(tab), 'search': self.focus_search,
            'location': self.pathbar.edit, 'connect': self.connect_to_server, 'reload': lambda: tab.load(keep_selection=True),
            'view-icons': lambda: self.view('icons'), 'view-list': lambda: self.view('list'),
            'view-columns': lambda: self.view('columns'), 'view-cover': lambda: self.view('cover'),
            'back': tab.go_back, 'forward': tab.go_forward, 'toggle-hidden': self.toggle_hidden, 'empty-trash': self.empty_trash,
            'extract': self.extract_selection, 'compress': lambda: self.compress_selection('zip'),
            'quicklook': self.toggle_quicklook, 'escape': self._escape, 'rename': self.rename_selection,
            'zoom-in': lambda: self.zoom.set_value(self.zoom.get_value() + 16), 'zoom-out': lambda: self.zoom.set_value(self.zoom.get_value() - 16),
            'next-tab': lambda: self.tabs.next_page(),
        }.get(name)
        if handler is None:
            return False
        if name in ('quicklook',) and not sel and not self.quicklook.visible():
            return True
        handler()
        return True

    def _escape(self):
        if self.quicklook.visible():
            self.quicklook.close()
        elif self.current.loc.kind == 'search':
            self.end_search()

    # ------------------------------------------------------------ opening
    def activate_entry(self, entry, tab=None, from_ql=False):
        tab = tab or self.current
        if entry.is_dir:
            if entry.path and tab.loc.kind != 'remote' or entry.path:
                self.open_location(Loc.dir(entry.path))
            elif entry.uri:
                if tab.loc.kind == 'network' or tab.loc.kind == 'remote':
                    self.open_remote(entry.uri)
                else:
                    self.open_location(Loc.remote(entry.uri))
            return
        self.open_entry(entry)

    def open_entry(self, entry, app_info=None):
        try:
            check_openable(entry.mime, entry.path)
            uri = Gio.File.new_for_path(entry.path).get_uri() if entry.path else entry.uri
            ctx = launch_context()
            if app_info is not None:
                app_info.launch_uris([uri], ctx)
            else:
                Gio.AppInfo.launch_default_for_uri(uri, ctx)
            if entry.path:
                try:
                    Gtk.RecentManager.get_default().add_item(uri)
                except Exception:
                    pass
        except OpenRefused as exc:
            sheets.message(self, 'Cannot open', str(exc))
        except GLib.Error as exc:
            sheets.message(self, 'Cannot open file', exc.message or 'No application is available for this kind of file.')

    def open_selection(self):
        entries = self.current.selected_entries()
        if not entries:
            return
        dirs = [e for e in entries if e.is_dir]
        if len(entries) == 1:
            self.activate_entry(entries[0])
            return
        for e in entries:
            if e.is_dir:
                self.new_tab(Loc.dir(e.path) if e.path else Loc.remote(e.uri))
            else:
                self.open_entry(e)

    def go_parent(self):
        tab = self.current
        if tab.view is not None and tab.view.mode == 'columns':
            tab.view.clear_from(max(1, len(tab.view.columns) - 1))
            col = tab.view.columns[-1]
            tab.columns_navigated(col.path, None)
            return
        parent = tab.loc.parent()
        if parent is not None:
            child = tab.loc.path if tab.loc.kind == 'dir' else None
            tab.navigate(parent, select=child)

    def toggle_quicklook(self):
        sel = self.current.selected_entries()
        if self.quicklook.visible():
            self.quicklook.close()
        elif sel:
            self.quicklook.show(sel[0])

    def step_selection(self, delta):
        tab = self.current
        tab.view.step(delta)

    def get_info(self):
        tab = self.current
        sel = tab.selected_entries()
        if not sel:
            if tab.loc.kind == 'dir':
                try:
                    sel = [model.stat_entry(tab.loc.path)]
                except OSError:
                    return
            else:
                return
        getinfo.GetInfo(self, sel)

    # ------------------------------------------------------------ operations
    def selected_locations(self):
        return [e.location for e in self.current.selected_entries() if e.location]

    def current_folder(self):
        t = self.current
        if t.loc.kind == 'dir':
            return t.loc.path
        if t.loc.kind == 'remote':
            return t.loc.uri
        return None

    def new_folder(self):
        folder = self.current_folder()
        if not folder:
            sheets.message(self, 'New Folder', 'Open a folder first: new folders cannot be created in this list.')
            return
        job = self.engine.new_folder(folder)
        job.opts['reveal_rename'] = True

    def rename_selection(self):
        tab = self.current
        items = tab.selected_items()
        if len(items) != 1:
            return
        self.begin_rename(items[0], tab)

    def begin_rename(self, item, tab):
        if tab.loc.kind == 'trash':
            return
        ok = False
        if tab.view is not None and tab.view.mode in ('icons', 'list', 'columns', 'cover'):
            ok = tab.view.rename(item)
        if not ok:
            e = item.entry
            sheets.ask_name(self, 'Rename', f'New name for “{e.name}”:', e.name, 'Rename',
                            lambda name: self.rename_entry(e, name, tab), select_stem=not e.is_dir)

    def rename_entry(self, entry, name, tab):
        if not entry.location:
            return
        self.engine.rename(entry.location, name)

    def duplicate_selection(self):
        locs = self.selected_locations()
        if locs and self.current.loc.kind in ('dir', 'remote'):
            self.engine.duplicate(locs)

    def trash_selection(self):
        tab = self.current
        entries = tab.selected_entries()
        if not entries:
            return
        if tab.loc.kind == 'trash':
            self.delete_selection()
            return
        self.engine.trash([e.location for e in entries if e.location])

    def delete_selection(self):
        entries = self.current.selected_entries()
        if not entries:
            return
        n = len(entries)
        name = f'“{entries[0].name}”' if n == 1 else f'these {n} items'
        locs = [e.location for e in entries]
        trashed = [e.extra['trash'] for e in entries if 'trash' in e.extra]
        sheets.confirm(self, 'Delete Immediately?', f'Are you sure you want to permanently delete {name}?',
                       'Delete Immediately', lambda: self._delete_now(locs, trashed), destructive=True,
                       detail='You cannot undo this action.')

    def _delete_now(self, locs, trashed):
        if trashed:
            def run(job):
                for t in trashed:
                    job.check()
                    try:
                        trashlib.delete_item(t)
                        job.done_items += 1
                    except Exception as exc:
                        job.fail(t.name, getattr(exc, 'message', None) or str(exc))
            job = ops.Job('delete', [], None, 'Delete')
            job.undoable = False
            job.total_items = len(trashed)
            self.engine.submit(job, run)
        else:
            self.engine.delete(locs)

    def empty_trash(self):
        if trashlib.is_empty():
            sheets.message(self, 'Empty Trash', 'The Trash is already empty.')
            return
        n = len(trashlib.list_trash())
        sheets.confirm(self, 'Empty the Trash?', f'The {n} item' + ('' if n == 1 else 's') +
                       ' in the Trash will be permanently erased.', 'Empty Trash', self.engine.empty_trash,
                       destructive=True, detail='You cannot undo this action.')

    def put_back(self):
        items = [e.extra['trash'] for e in self.current.selected_entries() if 'trash' in e.extra]
        if items:
            self.engine.restore(items)

    def trash_locations(self, locations):
        self.engine.trash(locations)

    def undo(self):
        if self.engine.can_undo:
            self.engine.undo()

    def redo(self):
        if self.engine.can_redo:
            self.engine.redo()

    def compress_selection(self, fmt='zip'):
        entries = self.current.selected_entries()
        folder = self.current_folder()
        if not entries or not folder or any(not e.path for e in entries):
            return
        parent = os.path.dirname(entries[0].path) if self.current.loc.kind != 'dir' else folder
        self.engine.compress([e.path for e in entries], parent, fmt)

    def extract_selection(self):
        for e in self.current.selected_entries():
            if e.path and not e.is_dir and archive.is_archive(e.path):
                self.engine.extract(e.path)

    def drop_into(self, locations, dest, ctrl):
        """Copy or move dropped items into ``dest`` (path or URI). Skips no-ops and refuses to nest a folder in itself."""
        locations = [l for l in locations if l]
        if not locations or not dest:
            return False
        try:
            if '://' not in dest and not os.path.isdir(dest):
                return False
        except OSError:
            return False
        sources = []
        for s in locations:
            if '://' not in s and '://' not in dest and os.path.dirname(os.path.abspath(s)) == os.path.abspath(dest) and not ctrl:
                continue          # dropping onto the folder it already lives in
            sources.append(s)
        if not sources:
            return True
        copy = dnd.default_copy(sources, dest, ctrl)
        (self.engine.copy if copy else self.engine.move)(sources, dest)
        return True

    # ------------------------------------------------------------ clipboard
    def copy_selection(self, cut):
        tab = self.current
        items = tab.selected_items()
        locs = [i.entry.location for i in items if i.entry.location]
        if not locs:
            return
        self._clear_cut()
        uris = [Gio.File.new_for_path(l).get_uri() if '://' not in l else l for l in locs]
        gnome = ('cut\n' if cut else 'copy\n') + '\n'.join(uris)
        providers = [dnd.provider_for(locs),
                     Gdk.ContentProvider.new_for_bytes('x-special/gnome-copied-files', GLib.Bytes.new(gnome.encode())),
                     Gdk.ContentProvider.new_for_bytes('text/plain;charset=utf-8', GLib.Bytes.new('\n'.join(locs).encode()))]
        Gdk.Display.get_default().get_clipboard().set_content(Gdk.ContentProvider.new_union(providers))
        self.clip = ('cut' if cut else 'copy', locs)
        if cut:
            for i in items:
                i.cut = True
                tab.view.refresh_cell(i)
            self._cut_items = items
        self.set_status(('Cut ' if cut else 'Copied ') + f'{len(locs)} item' + ('' if len(locs) == 1 else 's'))

    def _clear_cut(self):
        for i in getattr(self, '_cut_items', []):
            i.cut = False
            if self.current and self.current.view:
                self.current.view.refresh_cell(i)
        self._cut_items = []

    def paste(self, dest=None):
        dest = dest or self.current_folder()
        if not dest:
            return
        sel = self.current.selected_entries()
        if dest == self.current_folder() and len(sel) == 1 and sel[0].is_dir and sel[0].location:
            dest = sel[0].location                    # "Paste into" a selected folder
        cb = Gdk.Display.get_default().get_clipboard()

        def done(clipboard, result):
            try:
                stream, mime = clipboard.read_finish(result)
                data = stream.read_bytes(4 * 1024 * 1024, None).get_data().decode('utf-8', 'replace')
            except GLib.Error:
                self.set_status('Nothing to paste.')
                return
            cut, locs = self.parse_clipboard(data, mime)
            if not locs:
                self.set_status('Nothing to paste.')
                return
            if cut:
                if not self.drop_into(locs, dest, False):
                    return
                self._clear_cut()
            else:
                self.engine.copy(locs, dest)
        cb.read_async(['x-special/gnome-copied-files', 'text/uri-list'], GLib.PRIORITY_DEFAULT, None, done)

    @staticmethod
    def parse_clipboard(data, mime):
        lines = [l.strip() for l in data.replace('\r', '').split('\n') if l.strip() and not l.startswith('#')]
        cut = False
        if mime == 'x-special/gnome-copied-files' and lines and lines[0] in ('cut', 'copy'):
            cut = lines[0] == 'cut'
            lines = lines[1:]
        locs = []
        for l in lines:
            if l.startswith('file://'):
                p = Gio.File.new_for_uri(l).get_path()
                if p:
                    locs.append(p)
            elif '://' in l:
                locs.append(l)
        return cut, locs

    # ------------------------------------------------------------ jobs finishing
    def _job_done(self, job):
        kind = job.kind
        local_tabs = [t for t in self.tabs_list if t.loc.kind == 'dir']
        # removals
        if kind in ('trash', 'delete', 'move', 'rename'):
            for src in job.sources:
                p = src.get_path()
                if p:
                    for t in local_tabs:
                        if os.path.dirname(p) == t.loc.path:
                            t.remove_path(p)
        for res in job.results:
            for t in local_tabs:
                if os.path.dirname(res) == t.loc.path:
                    t.upsert_path(res)
        if kind in ('undo', 'redo', 'restore', 'empty-trash', 'trash', 'delete'):
            for t in self.tabs_list:
                if t.loc.kind in ('trash', 'dir') and (kind in ('undo', 'redo') or t.loc.kind == 'trash'):
                    t.load(keep_selection=True)
        if kind in ('new-folder', 'new-file') and job.results and self.current is not None:
            self.current.reveal(job.results[0], rename=True)
        elif kind in ('copy', 'move', 'duplicate', 'compress', 'extract', 'restore') and job.results and self.current is not None:
            if self.current.loc.kind == 'dir' and os.path.dirname(job.results[0]) == self.current.loc.path:
                self.current.reveal(job.results[0])
        if kind in ('trash', 'restore', 'empty-trash', 'delete', 'undo', 'redo'):
            self.sidebar.refresh()
        if kind == 'move':
            self._clear_cut()
        if job.cancelled and not job.errors:
            self.set_status('Cancelled.')
            return
        candidates = job.opts.get('permanent_candidates') or []
        if kind == 'trash' and candidates:
            names = ', '.join(ops.display(c) for c in candidates[:3])
            locs = [c.get_path() or c.get_uri() for c in candidates]
            sheets.confirm(self, 'Cannot Move to Trash', f'{names} cannot be moved to the Trash (for example on a network '
                           'share or drive without a trash). Delete immediately?', 'Delete Immediately',
                           lambda: self.engine.delete(locs), destructive=True, detail='You cannot undo this action.')
            return
        if job.errors:
            verb = {'copy': 'copied', 'move': 'moved', 'trash': 'moved to the Trash', 'delete': 'deleted', 'rename': 'renamed',
                    'extract': 'extracted', 'compress': 'compressed', 'undo': 'undone', 'redo': 'redone',
                    'new-folder': 'created', 'new-file': 'created', 'restore': 'put back', 'duplicate': 'duplicated'}.get(kind, 'processed')
            lines = [e.strip(': ') for e in job.errors]
            if len(lines) == 1 and not job.results and job.done_items == 0:
                sheets.message(self, f'Could not be {verb}', lines[0])
            else:
                sheets.message(self, f'Some items could not be {verb}',
                               f'{job.done_items} item(s) succeeded, {len(job.errors)} failed.', lines)
        elif job.skipped and not job.done_items:
            self.set_status(f'Skipped {job.skipped} item(s).')

    # ------------------------------------------------------------ devices & network
    def mount_device(self, device, open_after=False):
        def done(vol, msg):
            if msg:
                sheets.message(self, 'Cannot mount', msg)
                return
            self.sidebar.refresh()
            if open_after:
                for d in network.devices():
                    if d.name == device.name and d.mounted:
                        loc = Loc.dir(d.path) if d.path else Loc.remote(d.uri)
                        self.open_location(loc)
                        break
        network.mount_device(device, self.win, done)

    def eject_device(self, device, eject=True):
        def done(ok, msg):
            if msg:
                sheets.message(self, 'Cannot eject' if eject else 'Cannot unmount', msg)
            self.sidebar.refresh()
        if self.current and self.current.loc.kind == 'dir' and device.path and self.current.loc.path.startswith(device.path):
            self.current.navigate(Loc.dir(Path.home()))
        network.unmount_device(device, self.win, done, eject=eject)

    def connect_to_server(self):
        sheets.connect_server(self, self.open_remote)

    def forget_server(self, uri):
        self.prefs['servers'] = [s for s in self.prefs['servers'] if s != uri]
        self.save_prefs()
        self.sidebar.refresh()

    def refresh_sidebar(self):
        self.sidebar.refresh()

    def refresh_entries(self, entries):
        """Re-read tags/permissions for entries after Get Info changed them."""
        for tab in self.tabs_list:
            if tab.view is None:
                continue
            for i in range(tab.store.get_n_items()):
                item = tab.store.get_item(i)
                if any(item.entry.path == e.path for e in entries):
                    tab.view.refresh_cell(item)
        self.sidebar.refresh()

    def toggle_hidden(self):
        self.prefs['show_hidden'] = not self.prefs['show_hidden']
        self.save_prefs()
        for t in self.tabs_list:
            if t.loc.kind != 'search':
                t.load(keep_selection=True)

    # ------------------------------------------------------------ menus
    def _fill_pop(self, pop, rows):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        from .widgets import _fill_menu
        _fill_menu(col, rows, pop)
        pop.set_child(col)

    def tag_row(self, entries):
        paths = [e.path for e in entries if e.path]
        row = ui.box(spacing=4)
        row.set_margin_start(6)
        row.set_margin_top(2)
        for name in tags.COLOURS:
            have = all(any(t.casefold() == name.casefold() for t in tags.STORE.get_tags(p)) for p in paths) if paths else False
            b = Gtk.ToggleButton(active=have, tooltip_text=name)
            b.add_css_class('tag-toggle')
            b.add_css_class('tagdot-' + name.casefold())
            b.set_child(Gtk.Label(label='●'))
            b.connect('clicked', lambda btn, n=name: (tags.STORE.toggle_tag(paths, n), self.refresh_entries(entries)))
            row.append(b)
        return row

    def arrange_rows(self):
        tab = self.current
        mark = lambda on: '✓ ' if on else '    '
        rows = [('title', 'SORT BY')]
        for key, label in (('name', 'Name'), ('modified', 'Date Modified'), ('created', 'Date Created'), ('size', 'Size'), ('kind', 'Kind')):
            rows.append((mark(tab.sort_key == key) + label, lambda k=key: tab.sort_changed(k, tab.sort_reverse)))
        rows.append(None)
        rows.append((mark(not tab.sort_reverse) + 'Ascending', lambda: tab.sort_changed(tab.sort_key, False)))
        rows.append((mark(tab.sort_reverse) + 'Descending', lambda: tab.sort_changed(tab.sort_key, True)))
        rows.append(None)
        rows.append((mark(self.prefs['folders_first']) + 'Keep Folders on Top', self._toggle_folders_first))
        rows.append((mark(self.prefs['show_hidden']) + 'Show Hidden Files', self.toggle_hidden))
        return rows

    def _toggle_folders_first(self):
        self.prefs['folders_first'] = not self.prefs['folders_first']
        self.save_prefs()
        self.current.resort()

    def open_with_rows(self, entry):
        rows = []
        if entry.is_dir or not entry.mime:
            return rows
        default = Gio.AppInfo.get_default_for_type(entry.mime, False)
        for app in Gio.AppInfo.get_all_for_type(entry.mime)[:12]:
            name = app.get_display_name() + ('  (default)' if default and app.get_id() == default.get_id() else '')
            rows.append((name, lambda a=app: self.open_entry(entry, a)))
        return rows or [('No applications available', lambda: None, False)]

    def selection_rows(self, entries, tab):
        n = len(entries)
        e0 = entries[0]
        in_trash = tab.loc.kind == 'trash'
        rows = []
        if in_trash:
            rows += [('Put Back', self.put_back), ('Delete Immediately…', self.delete_selection), None,
                     ('Quick Look', self.toggle_quicklook), ('Get Info', self.get_info)]
            return rows
        rows.append(('Open', self.open_selection))
        if n == 1 and e0.is_dir:
            rows.append(('Open in New Tab', lambda: self.new_tab(Loc.dir(e0.path) if e0.path else Loc.remote(e0.uri))))
        if n == 1 and not e0.is_dir:
            rows.append(('submenu', 'Open With', self.open_with_rows(e0)))
        if tab.loc.virtual and e0.path:
            rows.append(('Show Enclosing Folder', lambda: (self.open_location(Loc.dir(os.path.dirname(e0.path))), self.current.reveal(e0.path))))
        rows += [('Quick Look', self.toggle_quicklook), ('Get Info', self.get_info), None]
        folder_ok = self.current_folder() is not None
        if n == 1 and folder_ok:
            rows.append(('Rename', self.rename_selection))
        rows.append(('Duplicate', self.duplicate_selection, folder_ok))
        if n == 1 and e0.path and not e0.is_dir and archive.is_archive(e0.path):
            rows.append(('Extract Here', self.extract_selection))
        rows.append(('submenu', 'Compress', [('as ZIP', lambda: self.compress_selection('zip')),
                                             ('as tar.gz', lambda: self.compress_selection('tar.gz')),
                                             ('as tar.xz', lambda: self.compress_selection('tar.xz'))]))
        rows.append(('Move to Trash', self.trash_selection))
        rows += [None, ('Copy', lambda: self.copy_selection(False)), ('Cut', lambda: self.copy_selection(True))]
        if n == 1 and e0.is_dir and folder_ok:
            rows.append(('Paste into Folder', self.paste))
        rows.append(('Copy as Path', lambda: Gdk.Display.get_default().get_clipboard().set('\n'.join(e.path or e.uri for e in entries))))
        if any(e.path for e in entries):
            rows += [None, ('title', 'TAGS'), ('widget', self.tag_row(entries))]
        return rows

    def background_rows(self, tab):
        rows = []
        if tab.loc.kind == 'trash':
            return [('Empty Trash…', self.empty_trash, not trashlib.is_empty())]
        can = self.current_folder() is not None
        rows.append(('New Folder', self.new_folder, can))
        rows.append(('Paste', self.paste, can))
        rows.append(('Select All', lambda: tab.view.select_all()))
        rows.append(None)
        rows.append(('Get Info', self.get_info, tab.loc.kind == 'dir'))
        rows.append(('submenu', 'Sort By', self.arrange_rows()))
        rows.append(('Hide Hidden Files' if self.prefs['show_hidden'] else 'Show Hidden Files', self.toggle_hidden))
        return rows

    def context_menu(self, tab, item, widget, x, y, folder=None):
        if tab is not self.current:
            return
        if item is not None:
            if item not in tab.selected_items():
                tab.view.select_items([item])
            rows = self.selection_rows(tab.selected_entries(), tab)
        else:
            if tab.view.mode != 'columns':
                tab.view.select_items([])
            rows = self.background_rows(tab)
        popup_menu(widget, x, y, rows)

    def action_rows(self):
        tab = self.current
        sel = tab.selected_entries()
        rows = self.selection_rows(sel, tab) if sel else self.background_rows(tab)
        rows += [None]
        rows.append((f'Undo {self.engine.undo_label}'.strip(), self.undo, self.engine.can_undo))
        rows.append((f'Redo {self.engine.redo_label}'.strip(), self.redo, self.engine.can_redo))
        rows += [None, ('New Tab', self.new_tab), ('New Window', lambda: Files(self.app, self.path)),
                 ('Connect to Server…', self.connect_to_server), ('Empty Trash…', self.empty_trash, not trashlib.is_empty())]
        return rows
