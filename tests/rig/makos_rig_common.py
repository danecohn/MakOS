"""Helpers shared by the Settings and Seek rig scripts: main-loop spinning, widget screenshots, widget search."""
import os
import time
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import GLib, Graphene, Gtk  # noqa: E402

OUT = Path(os.environ['OUT'])


def spin(check, timeout=15):
    end = time.monotonic() + timeout
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if check():
            return
        time.sleep(.004)
    raise AssertionError('Timed out waiting for a condition')


def settle(seconds=.4):
    end = time.monotonic() + seconds
    spin(lambda: time.monotonic() >= end, seconds + 2)


def shot(widget, name):
    w, h = widget.get_width(), widget.get_height()
    assert w > 0 and h > 0, f'{name}: widget has no size'
    paint = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    paint.snapshot(snap, w, h)
    node = snap.to_node()
    tex = widget.get_renderer().render_texture(node, Graphene.Rect().init(0, 0, w, h))
    path = OUT / (name + '.png')
    tex.save_to_png(str(path))
    return path


def walk(widget):
    child = widget.get_first_child()
    while child:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


def find_all(widget, cls):
    return [w for w in walk(widget) if isinstance(w, cls)]


def texts(widget):
    out = []
    for w in walk(widget):
        if isinstance(w, Gtk.Label):
            out.append(w.get_text())
        elif isinstance(w, Gtk.Button) and w.get_label():
            out.append(w.get_label())
    return out
