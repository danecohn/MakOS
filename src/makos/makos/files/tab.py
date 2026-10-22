"""One Files tab: location, history, loading (always off the main thread), the current view and its host interface."""
import os
import threading
import time

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from .. import ui
from . import model, network, search as fsearch, tags, trash as trashlib, views
from .location import Loc
from .widgets import Item

CHUNK = 250


def idle(fn, *args):
    GLib.idle_add(lambda: (fn(*args), False)[1])


class Tab:
    def __init__(self, files, loc, mode=None):
        self.files = files
        self.loc = loc
        self.last_local = loc.path if loc.kind == 'dir' else os.path.expanduser('~')
        self.back, self.fwd = [], []
        self.mode = mode or files.prefs['view']
        self.sort_key = files.prefs['sort_key']
        self.sort_reverse = files.prefs['sort_reverse']
        if loc.kind == 'recent':
            self.sort_key, self.sort_reverse = 'modified', True
        self.store = Gio.ListStore.new(Item)
        self.view = None
        self.gen = 0
        self.cancel = threading.Event()
        self.monitor = None
        self.monitor_id = None
        self.pending_select = None        # (path, start_rename)
        self.search_handle = None
        self.search_origin = None
        self.message = ''                 # error / empty-state text
        self.loading = False
        self.page = Gtk.Overlay()
        self.holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.holder.set_hexpand(True)
        self.holder.set_vexpand(True)
        self.page.set_child(self.holder)
        self.banner = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=48)
        self.banner.add_css_class('empty-state')
        self.banner.set_halign(Gtk.Align.CENTER)
        self.banner.set_valign(Gtk.Align.CENTER)
        self.banner.set_can_target(False)
        self.banner.set_visible(False)
        self.page.add_overlay(self.banner)
        self.tab_label = Gtk.Label(label=loc.title, ellipsize=3, max_width_chars=22)
        self.refresh_after_ops = True

    # ------------------------------------------------ host interface used by views
    @property
    def icon_size(self):
        return self.files.prefs['icon_size']

    @property
    def virtual(self):
        return self.loc.virtual or self.loc.kind in ('network', 'remote')

    def show_error(self, text):
        self.files.set_status(text)

    def selection_changed(self):
        if self.files.current is self:
            self.files.selection_changed()

    def activate(self, item):
        if item is not None:
            self.files.activate_entry(item.entry, self)

    def blank_click(self):
        pass

    def context_menu(self, item, widget, x, y, folder=None):
        self.files.context_menu(self, item, widget, x, y, folder)

    def can_drop(self, target_item):
        return target_item is not None or self.loc.kind in ('dir', 'remote')

    def drop(self, locations, target_item, ctrl, folder=None):
        if target_item is not None:
            dest = target_item.entry.location
        elif folder:
            dest = folder
        elif self.loc.kind == 'dir':
            dest = self.loc.path
        elif self.loc.kind == 'remote':
            dest = self.loc.uri
        else:
            return False
        return self.files.drop_into(locations, dest, ctrl)

    def drag_locations(self, item):
        selected = self.selected_items()
        if item not in selected:
            self.view.select_items([item])
            selected = [item]
        return [i.entry.location for i in selected if i.entry.location]

    def sort_changed(self, key, reverse):
        if key == 'where':
            key = 'name'
        self.sort_key, self.sort_reverse = key, reverse
        self.files.prefs['sort_key'], self.files.prefs['sort_reverse'] = key, reverse
        self.files.save_prefs()
        self.resort()
        self.files.sync_toolbar()

    def rename_commit(self, item, text):
        text = text.strip()
        if text and text != item.entry.name:
            self.files.rename_entry(item.entry, text, self)

    def columns_navigated(self, path, item):
        """The columns view moved without a reload: keep the tab's location in step."""
        if self.loc.kind == 'dir' and self.loc.path != path:
            self.loc = Loc.dir(path)
            self.last_local = path
            self.tab_label.set_text(self.loc.title)
            self.watch()
            if self.files.current is self:
                self.files.location_changed(self, columns=True)

    # ------------------------------------------------ view management
    def effective_mode(self):
        if self.mode == 'columns' and self.loc.kind != 'dir':
            return 'list'
        return self.mode

    def build_view(self):
        mode = self.effective_mode()
        if self.view is not None:
            self.view.teardown()
            self.holder.remove(self.view.widget)
        if mode == 'icons':
            self.view = views.IconView(self, self.store)
        elif mode == 'list':
            self.view = views.ListView(self, self.store)
        elif mode == 'cover':
            self.view = views.CoverView(self, self.store)
        else:
            self.view = views.ColumnsView(self, self.loc.path)
        self.holder.append(self.view.widget)

    def set_mode(self, mode):
        if mode == self.mode and self.view is not None and self.view.mode == self.effective_mode():
            return
        selected = [i.entry.path for i in self.selected_items()] if self.view else []
        self.mode = mode
        self.build_view()
        self._update_banner()
        if self.view.mode != 'columns' and self.store.get_n_items() == 0 and not self.loading:
            self.load()
        elif selected:
            self.select_paths(selected)
        self.files.sync_toolbar()

    def selected_items(self):
        return self.view.selected_items() if self.view is not None else []

    def selected_entries(self):
        return [i.entry for i in self.selected_items()]

    def select_paths(self, paths):
        want = set(paths)
        items = [self.store.get_item(i) for i in range(self.store.get_n_items())]
        self.view.select_items([it for it in items if it.entry.location in want or it.entry.path in want])

    def _update_banner(self):
        text = self.message
        if not text and not self.loading and self.store.get_n_items() == 0 and self.effective_mode() != 'columns':
            text = {'trash': 'The Trash is empty.', 'recent': 'No recent items yet.', 'search': 'No matches found.',
                    'tag': 'No items have this tag yet.', 'network': 'No network locations were found.\nUse Connect to Server to add one.'}\
                .get(self.loc.kind, 'This folder is empty.')
        self.banner.set_text(text)
        self.banner.set_visible(bool(text))
        self.banner.remove_css_class('error')
        if self.message:
            self.banner.add_css_class('error')

    # ------------------------------------------------ navigation
    def navigate(self, loc, push=True, select=None):
        if push and loc != self.loc:
            self.back.append(self.loc)
            self.fwd.clear()
            del self.back[:-200]
        if loc.kind == 'dir':
            self.last_local = loc.path
        self.loc = loc
        self.tab_label.set_text(loc.title)
        self.load(select)

    def go_back(self):
        if self.back:
            self.fwd.append(self.loc)
            self.loc = self.back.pop()
            self.tab_label.set_text(self.loc.title)
            self.load()

    def go_forward(self):
        if self.fwd:
            self.back.append(self.loc)
            self.loc = self.fwd.pop()
            self.tab_label.set_text(self.loc.title)
            self.load()

    # ------------------------------------------------ loading
    def stop(self):
        self.cancel.set()
        if self.search_handle:
            self.search_handle.cancel()
            self.search_handle = None

    def watch(self):
        self.unwatch()
        path = None
        if self.loc.kind == 'dir':
            path = self.loc.path
        elif self.loc.kind == 'trash':
            path = os.path.join(trashlib.data_home(), 'Trash', 'files')
        if not path or not os.path.isdir(path):
            return
        try:
            gf = Gio.File.new_for_path(path)
            self.monitor = gf.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self.monitor_id = self.monitor.connect('changed', self._fs_event)
        except GLib.Error:
            self.monitor = None

    def unwatch(self):
        if self.monitor is not None:
            try:
                self.monitor.disconnect(self.monitor_id)
                self.monitor.cancel()
            except Exception:
                pass
        self.monitor = None

    def _fs_event(self, _mon, file, other, event):
        E = Gio.FileMonitorEvent
        if self.loc.kind == 'trash':
            if event in (E.CREATED, E.DELETED, E.MOVED_IN, E.MOVED_OUT):
                self._debounce_reload()
            return
        if self.view is not None and self.view.mode == 'columns':
            if event in (E.CREATED, E.DELETED, E.MOVED_IN, E.MOVED_OUT, E.RENAMED):
                self._debounce_reload()
            return
        path = file.get_path()
        if event in (E.DELETED, E.MOVED_OUT):
            self.remove_path(path)
        elif event == E.RENAMED and other is not None:
            self.remove_path(path)
            self.upsert_path(other.get_path())
        elif event in (E.CREATED, E.MOVED_IN, E.CHANGES_DONE_HINT, E.ATTRIBUTE_CHANGED):
            self.upsert_path(path)

    def _debounce_reload(self):
        if getattr(self, '_reload_id', 0):
            return
        self._reload_id = GLib.timeout_add(500, self._reload_now)

    def _reload_now(self):
        self._reload_id = 0
        self.load(keep_selection=True)
        return False

    def load(self, select=None, keep_selection=False):
        self.stop()
        self.cancel = threading.Event()
        cancel = self.cancel
        self.gen += 1
        gen = self.gen
        kept = [i.entry.location for i in self.selected_items()] if keep_selection and self.view else []
        self.message = ''
        self.loading = True
        self.search_handle = None
        loc = self.loc
        if self.view is None or self.view.mode != self.effective_mode():
            self.build_view()
        elif self.effective_mode() == 'list' and hasattr(self.view, 'show_where'):
            self.view.show_where(self.virtual)
        # reset store (collapses any expanded rows)
        if self.view.mode != 'columns':
            self.store.remove_all()
        self.pending_select = (select, False) if select else self.pending_select
        self._update_banner()
        self.files.location_changed(self)
        self.watch()
        if self.view.mode == 'columns':
            self.loading = False
            self.view.show_path(loc.path)
            self._update_banner()
            return
        if loc.kind == 'search':
            self._run_search(loc, gen, cancel)
            return
        sort = (self.sort_key, self.sort_reverse, self.files.prefs['folders_first'])
        hidden = self.files.prefs['show_hidden']
        t0 = time.monotonic()

        def finish(count, error=None):
            if gen != self.gen:
                return
            self.loading = False
            self.message = error or ''
            self._update_banner()
            self.files.listing_done(self, count, time.monotonic() - t0)
            if kept:
                self.select_paths(kept)
            elif self.pending_select and self.pending_select[0]:
                self._apply_pending()
            self.files.selection_changed()

        def deliver(items, last_count=None, error=None):
            if gen != self.gen:
                return
            if items:
                self.store.splice(self.store.get_n_items(), 0, items)
            if last_count is not None:
                finish(last_count, error)
            else:
                self.files.set_status(f'Loading… {self.store.get_n_items():,} items')

        def run():
            try:
                total = 0
                home = os.path.expanduser('~')
                if loc.kind == 'dir':
                    entries = list(model.list_local(loc.path, hidden, cancel))
                elif loc.kind in ('remote', 'network'):
                    entries = self._list_remote(loc, hidden, cancel, gen)
                elif loc.kind == 'trash':
                    entries = [self._trash_entry(t) for t in trashlib.list_trash()]
                elif loc.kind == 'recent':
                    entries = self._recent_entries()
                elif loc.kind == 'tag':
                    entries = []
                    for p in tags.STORE.paths_for(loc.arg):
                        try:
                            e = model.stat_entry(p)
                            entries.append(e)
                        except OSError:
                            pass
                else:
                    entries = []
                if cancel.is_set():
                    return
                entries = model.sort_entries(entries, *sort[:2], folders_first=sort[2]) if loc.kind != 'recent' else \
                    sorted(entries, key=lambda e: -e.mtime)
                items = [Item(e) for e in entries]
                total = len(items)
                if cancel.is_set():
                    return
                offset = 0
                def deliver_next():
                    nonlocal offset
                    if gen != self.gen or cancel.is_set():
                        return False
                    end = min(offset + CHUNK, total)
                    deliver(items[offset:end], total if end >= total else None)
                    offset = end
                    if end < total:
                        GLib.timeout_add(1, deliver_next)
                    return False
                idle(deliver_next)
            except model.FolderError as exc:
                idle(deliver, [], 0, str(exc))
            except Exception as exc:
                idle(deliver, [], 0, f'This location could not be opened: {exc}')
        threading.Thread(target=run, daemon=True, name='makos-files-list').start()

    def _list_remote(self, loc, hidden, cancel, gen):
        uri = 'network:///' if loc.kind == 'network' else loc.uri
        try:
            return list(network.list_gio(uri, hidden, cancel))
        except model.FolderError as exc:
            if loc.kind == 'remote' and 'not connected' in str(exc).lower() or 'not mounted' in str(exc).lower():
                raise
            raise

    @staticmethod
    def _trash_entry(t):
        try:
            e = model.stat_entry(t.file)
        except OSError:
            e = model.Entry(name=t.name, path=t.file)
        e.name = t.name
        e.orig_path = t.orig
        e.deleted = t.deleted
        e.where = os.path.dirname(t.orig) if t.orig else ''
        e.extra['trash'] = t
        return e

    def _recent_entries(self):
        out = []
        mgr = Gtk.RecentManager.get_default()
        for info in mgr.get_items():
            uri = info.get_uri()
            if not uri.startswith('file://'):
                continue
            path = Gio.File.new_for_uri(uri).get_path()
            if not path or not os.path.lexists(path):
                continue
            try:
                e = model.stat_entry(path)
            except OSError:
                continue
            e.mtime = info.get_visited() or info.get_modified() or e.mtime
            out.append(e)
        return out

    def _run_search(self, loc, gen, cancel):
        roots = [loc.root or os.path.expanduser('~')]
        found = []

        def on_hit(hit):
            if gen != self.gen:
                return
            try:
                e = hit.entry()
            except OSError:
                return
            e.extra['score'] = hit.score
            e.extra['snippet'] = hit.snippet
            found.append(e)
            self.store.append(Item(e))
            if self.store.get_n_items() % 20 == 0:
                self.files.set_status(f'Searching… {self.store.get_n_items()} found')

        def on_done():
            if gen != self.gen:
                return
            self.search_handle = None
            self.loading = False
            ordered = sorted((self.store.get_item(i) for i in range(self.store.get_n_items())),
                             key=lambda it: (-it.entry.extra.get('score', 0), -it.entry.mtime))
            self.store.splice(0, self.store.get_n_items(), ordered)
            self._update_banner()
            self.files.listing_done(self, self.store.get_n_items(), 0.0, searching=True)

        contents = self.files.search_contents
        self.search_handle = fsearch.search_async(loc.arg, on_hit, on_done, roots=roots, contents=contents,
                                                  show_hidden=self.files.prefs['show_hidden'], dispatch=idle, limit=2000)

    # ------------------------------------------------ incremental updates
    def _find(self, path):
        for i in range(self.store.get_n_items()):
            it = self.store.get_item(i)
            if it.entry.path == path:
                return i, it
        return None, None

    def remove_path(self, path):
        pos, it = self._find(path)
        if pos is not None:
            self.store.remove(pos)
            self._update_banner()
            self.files.listing_changed(self)

    def upsert_path(self, path):
        if self.loc.kind != 'dir' or not path or os.path.dirname(path.rstrip('/')) != self.loc.path.rstrip('/') and self.loc.path != path:
            return
        if os.path.basename(path).startswith('.') and not self.files.prefs['show_hidden']:
            return
        try:
            e = model.stat_entry(path)
        except OSError:
            self.remove_path(path)
            return
        e.where = self.loc.path
        pos, old = self._find(path)
        new = Item(e)
        if old is not None:
            selected = old in self.selected_items()
            self.store.remove(pos)
        else:
            selected = False
        idx = self._insert_index(e)
        self.store.insert(idx, new)
        if selected:
            self.view.select_items(self.selected_items() + [new])
        self._update_banner()
        if self.pending_select and self.pending_select[0] == path:
            self._apply_pending()
        self.files.listing_changed(self)

    def _insert_index(self, entry):
        lo, hi = 0, self.store.get_n_items()
        ff = self.files.prefs['folders_first']
        while lo < hi:
            mid = (lo + hi) // 2
            other = self.store.get_item(mid).entry
            if model.entry_less(other, entry, self.sort_key, self.sort_reverse, ff):
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _apply_pending(self):
        path, rename = self.pending_select
        if not path:
            return
        pos, it = self._find(path)
        if it is None:
            return
        self.pending_select = None
        self.view.select_items([it])
        if rename:
            GLib.idle_add(lambda: (self.files.begin_rename(it, self), False)[1])

    def reveal(self, path, rename=False):
        """Select ``path`` once it appears in this tab."""
        self.pending_select = (path, rename)
        pos, it = self._find(path)
        if it is not None:
            self._apply_pending()
        elif self.loc.kind == 'dir' and os.path.dirname(path) == self.loc.path:
            self.upsert_path(path)

    def resort(self):
        if self.view is None or self.view.mode == 'columns' or self.loc.kind == 'search':
            return
        entries = [self.store.get_item(i).entry for i in range(self.store.get_n_items())]
        selected = [i.entry.location for i in self.selected_items()]
        key, rev, ff = self.sort_key, self.sort_reverse, self.files.prefs['folders_first']
        gen = self.gen

        def work():
            ordered = model.sort_entries(entries, key, rev, ff) if self.loc.kind != 'recent' else sorted(entries, key=lambda e: -e.mtime if key == 'modified' else 0)
            items = [Item(e) for e in ordered]
            idle(apply, items)

        def apply(items):
            if gen != self.gen:
                return
            n = self.store.get_n_items()
            self.store.splice(0, n, items)
            if selected:
                self.select_paths(selected)
        threading.Thread(target=work, daemon=True, name='makos-files-sort').start()

    # ------------------------------------------------ helpers for views
    def list_async(self, path, callback):
        hidden = self.files.prefs['show_hidden']
        key, rev, ff = self.sort_key, self.sort_reverse, self.files.prefs['folders_first']

        def work():
            error = None
            try:
                entries = model.sort_entries(list(model.list_local(path, hidden)), key, rev, ff)
            except model.FolderError as exc:
                entries, error = [], str(exc)
            idle(callback, [Item(e) for e in entries], error)
        threading.Thread(target=work, daemon=True, name='makos-files-column').start()

    def load_children(self, item):
        path = item.entry.path
        depth = item.depth + 1
        hidden = self.files.prefs['show_hidden']
        key, rev, ff = self.sort_key, self.sort_reverse, self.files.prefs['folders_first']
        try:
            st = os.stat(path)
            ident = (st.st_dev, st.st_ino)
        except OSError:
            ident = None
        ancestors = frozenset(item.ancestors | ({ident} if ident else set()))
        store = item.children_store

        def work():
            try:
                entries = list(model.list_local(path, hidden))
            except model.FolderError:
                entries = []
            kids = []
            for e in model.sort_entries(entries, key, rev, ff):
                it = Item(e, depth, ancestors)
                if e.expandable:
                    try:
                        s = os.stat(e.path)
                        if (s.st_dev, s.st_ino) in ancestors:
                            e.is_dir = False        # a loop (bind mount): show but never expand
                    except OSError:
                        pass
                kids.append(it)
            idle(store.splice, 0, 0, kids)
        threading.Thread(target=work, daemon=True, name='makos-files-children').start()

    def close(self):
        self.stop()
        self.unwatch()
        if self.view is not None:
            self.view.teardown()
