"""Drag and drop helpers: text/uri-list in and out through Gdk.FileList."""
import os
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, Gio, GObject, Gtk

ACTIONS = Gdk.DragAction.COPY | Gdk.DragAction.MOVE


def gfiles(locations):
    return [Gio.File.new_for_uri(x) if '://' in x else Gio.File.new_for_path(x) for x in locations]


def provider_for(locations):
    fl = Gdk.FileList.new_from_list(gfiles(locations))
    return Gdk.ContentProvider.new_for_value(GObject.Value(Gdk.FileList, fl))


def locations_from(value):
    """Gdk.FileList (or list of Gio.File) -> list of paths / URIs."""
    files = value.get_files() if hasattr(value, 'get_files') else list(value)
    out = []
    for f in files:
        out.append(f.get_path() if f.get_path() else f.get_uri())
    return out


def same_filesystem(sources, dest):
    """True when moving would be a rename on one device (so the default drop action is Move)."""
    try:
        dev = os.stat(dest).st_dev
        return all(os.lstat(s).st_dev == dev for s in sources)
    except OSError:
        return False


def default_copy(sources, dest, ctrl_held):
    """Classic rule: Move on the same volume, Copy across volumes; Ctrl forces Copy."""
    if ctrl_held:
        return True
    if any('://' in s for s in sources) or '://' in str(dest):
        return True
    return not same_filesystem(sources, dest)


def attach_source(widget, get_locations, icon_for_drag=None):
    """DragSource on ``widget``; get_locations(x, y) -> list of paths/URIs or []."""
    src = Gtk.DragSource()
    src.set_actions(ACTIONS)

    def prepare(_s, x, y):
        locs = get_locations(x, y)
        return provider_for(locs) if locs else None

    def begin(s, drag):
        if icon_for_drag:
            paint = icon_for_drag()
            if paint is not None:
                s.set_icon(paint, 0, 0)
    src.connect('prepare', prepare)
    src.connect('drag-begin', begin)
    widget.add_controller(src)
    return src


def attach_target(widget, on_motion, on_drop, on_leave):
    """DropTarget on ``widget``. on_motion(x, y) -> bool accepts; on_drop(locations, x, y, ctrl) -> bool."""
    tgt = Gtk.DropTarget.new(Gdk.FileList, ACTIONS)

    def motion(_t, x, y):
        return ACTIONS if on_motion(x, y) else 0

    def drop(t, value, x, y):
        state = t.get_current_event_state() if hasattr(t, 'get_current_event_state') else 0
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        return bool(on_drop(locations_from(value), x, y, ctrl))
    tgt.connect('motion', motion)
    tgt.connect('drop', drop)
    tgt.connect('leave', lambda *_: on_leave())
    widget.add_controller(tgt)
    return tgt
