"""Sidebar: Places, Devices (mount/unmount/eject), Shared (network), Tags."""
import os
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk, Pango

from .. import ui
from . import dnd, network, tags, trash as trashlib, widgets
from .location import Loc


class Row(Gtk.ListBoxRow):
    def __init__(self, label, icon, loc=None, device=None, data=None, trailing=None, tag_colour=None):
        super().__init__()
        self.loc, self.device, self.data = loc, device, data
        box = ui.box(spacing=8)
        box.add_css_class('side-row')
        if tag_colour:
            dot = Gtk.Label(label='●')
            dot.add_css_class('tagdot')
            dot.add_css_class('tagdot-' + tag_colour)
            box.append(dot)
        elif icon:
            box.append(widgets.make_icon(icon, 18))
        self.label = Gtk.Label(label=label, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        box.append(self.label)
        if trailing is not None:
            box.append(trailing)
        self.set_child(box)


class Heading(Gtk.ListBoxRow):
    def __init__(self, text):
        super().__init__(selectable=False, activatable=False)
        self.set_child(Gtk.Label(label=text, xalign=0, css_classes=['source-heading']))


class Sidebar(Gtk.ScrolledWindow):
    def __init__(self, files):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.files = files
        self.add_css_class('source-list')
        self.add_css_class('files-sidebar')
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class('side-list')
        self.set_child(self.list)
        self.list.connect('row-activated', self._activated)
        self.list.connect('row-selected', lambda *_: None)
        self._pending = 0
        self._current = None
        self.monitor = Gio.VolumeMonitor.get()
        for sig in ('mount-added', 'mount-removed', 'mount-changed', 'volume-added', 'volume-removed', 'volume-changed',
                    'drive-connected', 'drive-disconnected'):
            self.monitor.connect(sig, lambda *_: self.schedule())
        menu = Gtk.GestureClick(button=3)
        menu.connect('pressed', self._context)
        self.list.add_controller(menu)
        self.refresh()

    def schedule(self):
        if not self._pending:
            self._pending = GLib.timeout_add(180, self._deferred)

    def _deferred(self):
        self._pending = 0
        self.refresh()
        return False

    # -- build
    def refresh(self):
        child = self.list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list.remove(child)
            child = nxt
        home = Path.home()
        self.list.append(Heading('PLACES'))
        self._add(Row('Recents', 'folder-recent', Loc('recent')))
        self._add(Row('Home', 'folder-home', Loc.dir(home)))
        for name in ('Desktop', 'Documents', 'Downloads', 'Pictures', 'Music', 'Videos'):
            p = home / name
            if p.is_dir():
                self._add(Row(name, Loc.dir(p).icon, Loc.dir(p)))
        self._add(Row('Trash', 'trash-empty' if trashlib.is_empty() else 'trash-full', Loc('trash')))
        self.list.append(Heading('DEVICES'))
        self._add(Row('Computer', 'drive-internal', Loc.dir('/')))
        try:
            devs = network.devices()
        except Exception:
            devs = []
        shared = []
        for d in devs:
            if d.network:
                shared.append(d)
                continue
            trailing = None
            if d.mounted and (d.can_unmount or d.can_eject):
                trailing = Gtk.Button(label='⏏', has_frame=False, tooltip_text='Eject' if d.can_eject else 'Unmount')
                trailing.add_css_class('eject-button')
                trailing.connect('clicked', lambda _b, d=d: self.files.eject_device(d))
            loc = Loc.dir(d.path) if d.path else None
            self._add(Row(d.name, d.icon, loc, device=d, trailing=trailing))
        self.list.append(Heading('SHARED'))
        self._add(Row('Network', 'folder-network', Loc('network')))
        for d in shared:
            trailing = Gtk.Button(label='⏏', has_frame=False, tooltip_text='Disconnect')
            trailing.add_css_class('eject-button')
            trailing.connect('clicked', lambda _b, d=d: self.files.eject_device(d))
            loc = Loc.dir(d.path) if d.path else Loc.remote(d.uri)
            self._add(Row(d.name, 'drive-network', loc, device=d, trailing=trailing))
        for uri in self.files.prefs['servers'][:8]:
            self._add(Row(Loc.remote(uri).title + ' (' + uri.split('://')[0] + ')', 'network-server', Loc.remote(uri), data=('server', uri)))
        self._add(Row('Connect to Server…', 'network-server', None, data=('connect', None)))
        self.list.append(Heading('TAGS'))
        for name in tags.STORE.known_tags():
            colour = name.casefold() if name.title() in tags.COLOURS else 'custom'
            self._add(Row(name, None, Loc('tag', arg=name), tag_colour=colour, data=('tag', name)))
        self._reselect()

    def _add(self, row):
        self.list.append(row)
        if row.loc is not None or row.device is not None:
            self._drop_target(row)

    def _drop_target(self, row):
        loc = row.loc

        def motion(x, y):
            row.add_css_class('drop-target')
            return loc is not None and loc.kind in ('dir', 'trash', 'remote')

        def drop(locations, x, y, ctrl):
            row.remove_css_class('drop-target')
            if loc is None:
                return False
            if loc.kind == 'trash':
                self.files.trash_locations(locations)
                return True
            if loc.kind == 'dir':
                return self.files.drop_into(locations, loc.path, ctrl)
            if loc.kind == 'remote':
                return self.files.drop_into(locations, loc.uri, True)
            return False
        dnd.attach_target(row, motion, drop, lambda: row.remove_css_class('drop-target'))

    # -- state
    def select(self, loc):
        self._current = loc
        self._reselect()

    def _reselect(self):
        want = self._current
        child = self.list.get_first_child()
        picked = None
        while child:
            if isinstance(child, Row) and child.loc is not None and want is not None and child.loc == want:
                picked = child
                break
            child = child.get_next_sibling()
        if picked is not None:
            self.list.select_row(picked)
        else:
            self.list.unselect_all()

    # -- actions
    def _activated(self, _list, row):
        if not isinstance(row, Row):
            return
        if row.data and row.data[0] == 'connect':
            self.files.connect_to_server()
            return
        if row.device is not None and not row.device.mounted:
            self.files.mount_device(row.device, open_after=True)
            return
        if row.loc is not None:
            self.files.open_location(row.loc)

    def _context(self, gesture, n, x, y):
        row = self.list.get_row_at_y(int(y))
        if not isinstance(row, Row):
            return
        rows = []
        if row.loc is not None:
            rows.append(('Open', lambda: self.files.open_location(row.loc)))
            rows.append(('Open in New Tab', lambda: self.files.new_tab(row.loc)))
        if row.device is not None:
            d = row.device
            if not d.mounted:
                rows.append(('Mount', lambda: self.files.mount_device(d)))
            if d.mounted and d.can_unmount:
                rows.append(('Unmount', lambda: self.files.eject_device(d, eject=False)))
            if d.can_eject:
                rows.append(('Eject', lambda: self.files.eject_device(d)))
        if row.data and row.data[0] == 'server':
            rows.append(('Remove from Favorites', lambda: self.files.forget_server(row.data[1])))
        if row.loc is not None and row.loc.kind == 'trash':
            rows.append(None)
            rows.append(('Empty Trash…', self.files.empty_trash, not trashlib.is_empty()))
        if rows:
            widgets.popup_menu(self.list, x, y, rows)
