"""The Launcher Bar: a magnifying application bar drawn as one custom widget in one layer-shell surface.

Everything is painted from the widget's snapshot (icons are textures, the shelf is nine-sliced artwork), so magnification
is continuous and costs one render node per item instead of a CSS relayout. A frame callback runs only while something
is moving (pointer smoothing, bounce, slide, poof, drag); an idle bar redraws nothing.

Features: Gaussian magnification, 2D glass and 3D floor shelves with reflections, running indicators, bounce on launch,
drag to reorder and drag off to remove (poof), Keep/Remove/Show in Files/Hide/Quit menus, Downloads/Documents stacks
(fan or grid), badges, minimized windows with thumbnails, bottom/left/right placement and every auto-hide case.
All maths lives in dockmath.py / launcher.py (unit tested); this file is GTK glue.
"""
import math
import os
import time
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gsk', '4.0')
gi.require_version('Graphene', '1.0')
gi.require_version('Pango', '1.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

try:
    import cairo
except ImportError:  # pragma: no cover
    cairo = None

from .. import badges as badge_mod
from .. import catalog, common, ui
from . import dockmath as dm
from . import launcher as lm
from . import layer
from .launcher import Item

_DEBUG = bool(os.environ.get('MAKOS_DEBUG_DOCK'))
STYLES = ('glass', 'shelf3d')
HOVER_PAD = 8


def _rect(x, y, w, h):
    if _DEBUG and not (w >= 0 and h >= 0 and math.isfinite(x) and math.isfinite(y) and math.isfinite(w) and math.isfinite(h)):
        import traceback
        print('DOCK_BAD_RECT', (x, y, w, h), flush=True)
        traceback.print_stack(limit=4)
    return Graphene.Rect().init(x, y, w, h)


def _point(x, y):
    return Graphene.Point().init(x, y)


def _rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def _stops(*pairs):
    out = []
    for offset, color in pairs:
        s = Gsk.ColorStop()
        s.offset = offset
        s.color = color
        out.append(s)
    return out


LEAVE_GRACE_MS = 220


class IconCache:
    """Textures for theme icons, rendered once at 256 px (SVG icons through gdk-pixbuf)."""

    def __init__(self):
        self.cache = {}

    def get(self, name):
        if name in self.cache:
            return self.cache[name]
        tex = None
        base = common.SHARE / 'icons/MakkOS'
        for candidate in (base / '256x256/apps' / (name + '.png'), base / '128x128/apps' / (name + '.png'),
                          base / 'scalable/apps' / ('makos-' + name + '.svg'), base / 'scalable/apps' / (name + '.svg')):
            if candidate.exists():
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file_at_size(str(candidate), 256, 256)
                    tex = Gdk.Texture.new_for_pixbuf(pix)
                    break
                except GLib.Error:
                    continue
        if tex is None and name != 'file-generic':
            tex = self.get('file-generic')
        self.cache[name] = tex
        return tex


class Material:
    """Nine-sliced shelf artwork: left cap, 16-px stretchable middle, right cap."""

    def __init__(self, name):
        self.parts = []
        root = common.SHARE / 'theme/materials'
        for suffix in ('left', 'mid', 'right'):
            path = root / f'{name}-{suffix}.png'
            try:
                self.parts.append(Gdk.Texture.new_from_filename(str(path)))
            except GLib.Error:
                self.parts = []
                break
        self.ok = len(self.parts) == 3

    def draw(self, snap, x, y, w, h):
        """Draw the shelf art into the rectangle; caps keep the art's aspect, the middle stretches. All edges are snapped
        to whole pixels so neighbouring pieces never overlap (translucent art would show a seam)."""
        left, mid, right = self.parts
        x, y, w, h = round(x), round(y), round(w), round(h)
        s = h / left.get_height()
        cap_l, cap_r = round(left.get_width() * s), round(right.get_width() * s)
        if w < cap_l + cap_r:
            k = w / (cap_l + cap_r)
            cap_l, cap_r = round(cap_l * k), round(cap_r * k)
        snap.append_scaled_texture(left, Gsk.ScalingFilter.TRILINEAR, _rect(x, y, cap_l, h))
        snap.append_scaled_texture(right, Gsk.ScalingFilter.TRILINEAR, _rect(x + w - cap_r, y, cap_r, h))
        if w > cap_l + cap_r:
            snap.append_scaled_texture(mid, Gsk.ScalingFilter.NEAREST, _rect(x + cap_l, y, w - cap_l - cap_r, h))


class DockView(Gtk.Widget):
    __gtype_name__ = 'MakosDockView'

    def __init__(self, dock):
        super().__init__()
        self.dock = dock
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def do_measure(self, orientation, for_size):
        w, h = self.dock.surface_size()
        n = w if orientation == Gtk.Orientation.HORIZONTAL else h
        return (n, n, -1, -1)

    def do_snapshot(self, snap):
        self.dock.paint(self, snap)


class Dock:
    def __init__(self, shell):
        self.shell = shell
        self.prefs = shell.preferences
        self.icons = IconCache()
        self.materials = {}
        self.items = []
        self.badges = {}
        self.windows = []
        # pointer / animation state
        self.pointer = None            # (u, v) in surface coordinates, None when the pointer is elsewhere
        self.p_s = 0.0                 # smoothed pointer u
        self.strength = 0.0
        self.slide = 0.0               # 0 shown .. 1 hidden
        self.bounces = {}              # key -> start time
        self.poofs = []                # (x, y, start, texture)
        self.press = None              # (index, x, y) of a press waiting to become a click or a drag
        self.drag = None               # dict while an item is being dragged
        self.anim_start = {}           # key -> displayed start while slots shift after a drag
        self.popover = None
        self.popover_item = None
        self.hover_key = None
        self.fullscreen = False
        self.autohide = dm.AutoHide()
        self.inside = False
        self._tick = 0
        self._last_frame = None
        self.frame_deltas = []
        self.record_frames = False
        self._region_state = None
        self.style = 'glass'
        self.pos = 'bottom'
        self.base = 56
        self.zoom = 1.0
        self.window = shell.surface('Launcher', 'top', ('bottom',), exclusive=0, keyboard='on_demand')
        self.view = DockView(self)
        self.window.set_child(self.view)
        self._controllers()
        self.window.connect('map', lambda *_: self._update_region(force=True))
        self.apply_preferences(self.prefs, first=True)
        self.window.present()
        self._update_region(force=True)

    # ------------------------------------------------------------------------------------------ geometry
    def _compute_geometry(self):
        base = self.base
        lengths = lm.item_lengths(self.items, base) if self.items else [float(base)] * 8
        self.lengths = lengths
        self.extra = dm.max_growth(lengths, self.zoom) / 2.0 + 10
        self.rest_origin = self.extra + dm.PAD
        self.main_len = dm.rest_total(lengths) + 2 * dm.PAD + 2 * self.extra
        icon_max = base * self.zoom
        if self.style == 'shelf3d':
            self.floor = base * 0.78
            self.v0 = self.floor * 0.5 + 5
            self.shelf_top = self.floor + 3
            self.reserve = self.v0 + base + 6
        else:
            self.floor = base + 16
            self.v0 = 12
            self.shelf_top = base + 20
            self.reserve = self.shelf_top + 6
        self.bounce_h = base * 0.7
        self.label_h = 34
        self.active_v = self.v0 + icon_max + 10
        self.cross_len = self.v0 + icon_max + self.bounce_h + self.label_h + 8
        self.hide_dist = self.reserve + 8

    def surface_size(self):
        if self.pos == 'bottom':
            return (int(self.main_len), int(self.cross_len))
        return (int(self.cross_len), int(self.main_len))

    def uv(self, x, y):
        w, h = self.surface_size()
        if self.pos == 'left':
            return (y, x)
        if self.pos == 'right':
            return (y, w - x)
        return (x, h - y)

    def xy(self, u, v):
        w, h = self.surface_size()
        return dm.to_xy(self.pos, u, v, w, h)

    # ------------------------------------------------------------------------------------------ preferences
    def apply_preferences(self, prefs, first=False):
        """Apply size, position, style, magnification, auto-hide and folders. Safe to call while running (live settings)."""
        self.prefs = prefs
        reduce = bool(prefs.get('reduce_motion'))
        self.base = int(prefs.get('launcher_size', 56))
        self.zoom = dm.zoom_factor(prefs.get('launcher_magnify_percent', 55)) if (prefs.get('launcher_magnify', True) and not reduce) else 1.0
        style = prefs.get('launcher_style', 'glass')
        self.style = style if style in STYLES else 'glass'
        self.pos = prefs.get('launcher_position', 'bottom')
        self.reduce = reduce
        self.autohide_on = bool(prefs.get('launcher_autohide'))
        self.rebuild_items(announce=False)
        self._apply_window()
        if not first:
            self.view.queue_resize()
            self.autohide.force(not self.autohide_on and not self.fullscreen or self.autohide.visible)
            self._request_frames()

    def _apply_window(self):
        self._compute_geometry()
        win = self.window
        ls = layer.LS
        edge = {'bottom': ls.Edge.BOTTOM, 'left': ls.Edge.LEFT, 'right': ls.Edge.RIGHT}[self.pos]
        for e in (ls.Edge.BOTTOM, ls.Edge.LEFT, ls.Edge.RIGHT, ls.Edge.TOP):
            ls.set_anchor(win, e, e == edge)
        ls.set_layer(win, ls.Layer.OVERLAY if self.fullscreen else ls.Layer.TOP)
        self._set_exclusive()
        self.view.set_size_request(*self.surface_size())
        self.view.queue_resize()
        self._update_region(force=True)

    def _set_exclusive(self):
        zone = 0 if (self.autohide_on or self.fullscreen) else int(self.reserve)
        layer.LS.set_exclusive_zone(self.window, zone)

    def set_fullscreen(self, on):
        """A full screen application is active: hide the bar (it returns after the pointer rests on its edge)."""
        on = bool(on)
        if on == self.fullscreen:
            return
        self.fullscreen = on
        ls = layer.LS
        ls.set_layer(self.window, ls.Layer.OVERLAY if on else ls.Layer.TOP)
        self._set_exclusive()
        if on:
            self.autohide.force(False)
        else:
            self.autohide.force(not self.autohide_on)
        self._request_frames()
        self._update_region(force=True)

    def reveal(self, seconds=2.0):
        """Show the bar now (hot corner / shortcut) and let it hide again after `seconds`."""
        self.autohide.force(True)
        self._reveal_until = time.monotonic() + seconds
        self._request_frames()

    # ------------------------------------------------------------------------------------------ items
    def rebuild_items(self, announce=True):
        prefs = dict(self.prefs)
        items = lm.build_items(prefs, self.windows, self.badges)
        trash = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'Trash/files'
        try:
            full = any(trash.iterdir())
        except OSError:
            full = False
        for it in items:
            if it.kind == 'trash':
                it.icon = 'trash-full' if full else 'trash-empty'
        changed = [(i.kind, i.key) for i in items] != [(i.kind, i.key) for i in self.items]
        self.items = items
        for it in items:
            if it.running and it.key in self.bounces and it.windows:
                self.bounces[it.key] = min(self.bounces[it.key], time.monotonic() - 99)  # window appeared: stop bouncing
        if changed:
            self._compute_geometry()
            self.view.set_size_request(*self.surface_size())
            self.view.queue_resize()
            self._update_region(force=True)
            self.anim_start.clear()
        self.view.queue_draw()

    def set_windows(self, windows):
        self.windows = list(windows)
        self.rebuild_items()

    def set_badges(self, counts):
        self.badges = dict(counts)
        self.rebuild_items()

    def start_bounce(self, key):
        if self.reduce:
            return
        self.bounces[key] = time.monotonic()
        self._request_frames()

    # ------------------------------------------------------------------------------------------ layout per frame
    def rest(self):
        return dm.rest_layout(self.lengths, origin=self.rest_origin)

    def displayed(self):
        """Placements of every item for the current animation state (pointer, magnification, drag preview)."""
        n = len(self.items)
        if not n:
            return []
        lengths = lm.item_lengths(self.items, self.base)
        order = list(range(n))
        if self.drag and self.drag.get('active'):
            order = self.drag['order']
        lens = [lengths[i] for i in order]
        magn = [self.items[i].kind != 'separator' for i in order]
        if self.drag and self.drag.get('active'):
            placed = dm.rest_layout(lens, origin=self.rest_origin)
        else:
            placed = dm.layout(lens, magn, self.p_s, self.strength, self.zoom, origin=self.rest_origin)
        out = [None] * n
        for slot, i in enumerate(order):
            out[i] = placed[slot]
        # slots glide after a reorder instead of snapping
        for i, p in enumerate(out):
            key = self.items[i].key
            if key in self.anim_start:
                out[i] = dm.Placement(self.anim_start[key], p.length)
        return out

    def item_rect(self, i, placed=None):
        """Surface-space rectangle (x, y, w, h) of item i's icon at its rest height (no bounce)."""
        placed = placed or self.displayed()
        p = placed[i]
        return self._icon_rect(p.start + p.length / 2.0, p.length, 0.0)

    def _icon_rect(self, u, size, lift):
        v = self.v0 - self.slide * self.hide_dist + lift
        if self.pos == 'bottom':
            _x, y = self.xy(u, v + size)
            return (u - size / 2.0, y, size, size)
        if self.pos == 'left':
            x, _y = self.xy(u, v)
            return (x, u - size / 2.0, size, size)
        x, _y = self.xy(u, v + size)
        return (x, u - size / 2.0, size, size)

    # ------------------------------------------------------------------------------------------ painting
    def material(self):
        name = 'dock-shelf-3d' if self.style == 'shelf3d' else 'dock-shelf-flat'
        if name not in self.materials:
            self.materials[name] = Material(name)
        return self.materials[name]

    def paint(self, view, snap):
        if not self.items:
            return
        placed = self.displayed()
        lift = {}
        now = time.monotonic()
        for key, t0 in list(self.bounces.items()):
            age = now - t0
            if age > 8.0:
                del self.bounces[key]
            else:
                lift[key] = dm.bounce_offset(age, self.bounce_h)
        self._paint_shelf(snap, placed)
        dragged = self.drag['index'] if self.drag and self.drag.get('active') else None
        for i, it in enumerate(self.items):
            if it.kind == 'separator' or i == dragged:
                continue
            self._paint_item(view, snap, it, placed[i], lift.get(it.key, 0.0))
        for i, it in enumerate(self.items):
            if it.kind != 'separator':
                self._paint_overlays(view, snap, it, placed[i], lift.get(it.key, 0.0), i)
        if dragged is not None:
            self._paint_dragged(view, snap)
        self._paint_label(view, snap, placed, lift)
        self._paint_poofs(view, snap, now)

    def _local(self, snap):
        """Push a transform so that drawing at (a, b) means u = a, v = -b relative to the screen edge."""
        w, h = self.surface_size()
        snap.save()
        if self.pos == 'bottom':
            snap.translate(_point(0, h - (-self.slide * self.hide_dist) * -1))
        elif self.pos == 'left':
            snap.translate(_point(-self.slide * self.hide_dist, 0))
            snap.rotate(90)
        else:
            snap.translate(_point(w + self.slide * self.hide_dist, 0))
            snap.scale(-1, 1)
            snap.rotate(90)

    def _paint_shelf(self, snap, placed):
        first, last = placed[0], placed[-1]
        a0 = first.start - dm.PAD
        a1 = last.start + last.length + dm.PAD
        flare = 16 if self.style == 'shelf3d' else 0
        a0 -= flare
        a1 += flare
        self._local(snap)
        # local frame: x = u along the bar, y = -v. The shelf occupies v in [3, shelf_top].
        if self.style == 'shelf3d':
            y, h = -(self.floor + 3), self.floor
        else:
            y, h = -(self.shelf_top - 2), self.shelf_top - 6
        mat = self.material()
        if mat.ok:
            mat.draw(snap, a0, y, a1 - a0, h)
        else:
            rr = Gsk.RoundedRect().init_from_rect(_rect(a0, y, a1 - a0, h), 14)
            snap.push_rounded_clip(rr)
            snap.append_linear_gradient(_rect(a0, y, a1 - a0, h), _point(0, y), _point(0, y + h),
                                        _stops((0, _rgba(.92, .96, 1, .8)), (1, _rgba(.55, .65, .78, .85))))
            snap.pop()
        snap.restore()

    def _icon_texture(self, it):
        if it.kind == 'window':
            return None
        return self.icons.get(it.icon) if it.icon else self.icons.get('file-generic')

    def _paint_item(self, view, snap, it, p, lift):
        size = p.length
        x, y, w, h = self._icon_rect(p.start + p.length / 2.0, size, lift)
        if it.kind == 'window':
            self._paint_window_card(snap, it, x, y, w, h)
            return
        tex = self.icons.get(it.icon) if it.icon else self.icons.get('file-generic')
        if tex is None:
            return
        self._paint_reflection(snap, tex, p, lift)
        snap.append_scaled_texture(tex, Gsk.ScalingFilter.TRILINEAR, _rect(x, y, w, h))

    def _paint_reflection(self, snap, tex, p, lift):
        """Mirror image of the icon on the shelf surface, fading out (3D style strongly, glass style faintly)."""
        if self.slide > 0.6 or os.environ.get('MAKOS_DOCK_NOREFLECT'):
            return
        strength = 0.42 if self.style == 'shelf3d' else 0.16
        size = p.length
        depth = min(size * 0.5, max(0.0, self.v0 - 3 - self.slide * self.hide_dist))
        if depth < 2:
            return
        u = p.start + p.length / 2.0
        x, y, w, h = self._icon_rect(u, size, 0.0)
        if self.pos == 'bottom':
            region = _rect(x, y + h, w, depth)
            grad = (_point(0, y + h), _point(0, y + h + depth))
            flip = (lambda s: (s.translate(_point(0, 2 * (y + h))), s.scale(1, -1)))
        elif self.pos == 'left':
            region = _rect(x - depth, y, depth, h)
            grad = (_point(x, 0), _point(x - depth, 0))
            flip = (lambda s: (s.translate(_point(2 * x, 0)), s.scale(-1, 1)))
        else:
            region = _rect(x + w, y, depth, h)
            grad = (_point(x + w, 0), _point(x + w + depth, 0))
            flip = (lambda s: (s.translate(_point(2 * (x + w), 0)), s.scale(-1, 1)))
        snap.push_clip(region)
        snap.push_mask(Gsk.MaskMode.ALPHA)
        snap.append_linear_gradient(region, grad[0], grad[1], _stops((0, _rgba(0, 0, 0, strength)), (1, _rgba(0, 0, 0, 0))))
        snap.pop()
        snap.save()
        flip(snap)
        snap.append_scaled_texture(tex, Gsk.ScalingFilter.LINEAR, _rect(x, y, w, h))
        snap.restore()
        snap.pop()
        snap.pop()

    def _paint_window_card(self, snap, it, x, y, w, h):
        tex = self.shell.thumbs.get(it.key) if getattr(self.shell, 'thumbs', None) else None
        aspect = (tex.get_width() / tex.get_height()) if tex else 1.3
        cw = w
        ch = min(h, cw / aspect)
        if aspect < 1:
            ch = h
            cw = ch * aspect
        cx, cy = x + (w - cw) / 2.0, y + (h - ch) / 2.0
        if self.pos == 'bottom':
            cy = y + h - ch
        rr = Gsk.RoundedRect().init_from_rect(_rect(cx, cy, cw, ch), 5)
        snap.push_rounded_clip(rr)
        if tex:
            snap.append_scaled_texture(tex, Gsk.ScalingFilter.TRILINEAR, _rect(cx, cy, cw, ch))
        else:
            snap.append_linear_gradient(_rect(cx, cy, cw, ch), _point(0, cy), _point(0, cy + ch),
                                        _stops((0, _rgba(.93, .96, 1)), (1, _rgba(.66, .74, .85))))
        snap.pop()
        snap.append_border(rr, [1, 1, 1, 1], [_rgba(1, 1, 1, .85)] * 4)
        app = self.icons.get(it.icon) if it.icon else None
        if app:
            s = min(cw, ch) * 0.46
            snap.append_scaled_texture(app, Gsk.ScalingFilter.TRILINEAR, _rect(cx + cw - s * 0.85, cy + ch - s * 0.85, s, s))

    def _paint_overlays(self, view, snap, it, p, lift, index):
        """Running indicator and badge."""
        u = p.start + p.length / 2.0
        size = p.length
        if it.running and it.kind == 'app':
            v = (7 if self.style == 'shelf3d' else 6) - self.slide * self.hide_dist
            cx, cy = self.xy(u, v)
            r = 3.0
            snap.append_radial_gradient(_rect(cx - r * 2, cy - r * 2, r * 4, r * 4), _point(cx, cy), r * 2, r * 2, 0, 1,
                                        _stops((0, _rgba(.85, .97, 1, 1)), (.45, _rgba(.35, .7, 1, .95)), (1, _rgba(.2, .5, 1, 0))))
        count = it.badge or 0
        if count > 0 and it.kind in ('app', 'folder'):
            x, y, w, h = self._icon_rect(u, size, lift)
            text = lm.badge_text(count)
            d = max(18.0, size * 0.36)
            bw = d if len(text) < 2 else d + (len(text) - 1) * d * 0.28
            bx, by = x + w - bw * 0.7, y - d * 0.25
            rr = Gsk.RoundedRect().init_from_rect(_rect(bx, by, bw, d), d / 2.0)
            snap.push_rounded_clip(rr)
            snap.append_linear_gradient(_rect(bx, by, bw, d), _point(0, by), _point(0, by + d),
                                        _stops((0, _rgba(1, .52, .48)), (.5, _rgba(.9, .2, .2)), (1, _rgba(.72, .1, .12))))
            snap.pop()
            snap.append_border(rr, [1.5] * 4, [_rgba(1, 1, 1, .95)] * 4)
            layout = view.create_pango_layout(text)
            desc = Pango.FontDescription.from_string('DejaVu Sans Bold %d' % max(8, round(d * 0.46)))
            layout.set_font_description(desc)
            tw, th = layout.get_pixel_size()
            snap.save()
            snap.translate(_point(bx + (bw - tw) / 2.0, by + (d - th) / 2.0))
            snap.append_layout(layout, _rgba(1, 1, 1))
            snap.restore()

    def _paint_dragged(self, view, snap):
        d = self.drag
        it = self.items[d['index']]
        size = self.base * (1.15)
        alpha = 0.55 if d.get('remove') else 0.95
        tex = self.icons.get(it.icon) if it.icon else None
        if tex is None:
            return
        u, v = d['u'], d['v']
        x, y = self.xy(u, v)
        snap.push_opacity(alpha)
        snap.append_scaled_texture(tex, Gsk.ScalingFilter.TRILINEAR, _rect(x - size / 2, y - size / 2, size, size))
        snap.pop()
        if d.get('remove'):
            self._text(view, snap, 'Remove', x, y - size / 2 - 22, centered=True, bg=True)

    def _paint_label(self, view, snap, placed, lift):
        if os.environ.get('MAKOS_DOCK_NOLABEL') or self.strength < 0.5 or self.drag or self.popover is not None or self.pointer is None or self.slide > 0.2:
            self.hover_key = None
            return
        i = dm.hit_index(placed, self.pointer[0])
        if i is None or self.items[i].kind == 'separator':
            self.hover_key = None
            return
        it = self.items[i]
        self.hover_key = it.key
        p = placed[i]
        u = p.start + p.length / 2.0
        x, y, w, h = self._icon_rect(u, p.length, lift.get(it.key, 0.0))
        if self.pos == 'bottom':
            self._text(view, snap, it.name, x + w / 2.0, y - 10, centered=True, bg=True, above=True)
        elif self.pos == 'left':
            self._text(view, snap, it.name, x + w + 8, y + h / 2.0, centered=False, bg=True, vcenter=True)
        else:
            self._text(view, snap, it.name, x - 8, y + h / 2.0, centered=False, bg=True, vcenter=True, right_align=True)

    def _text(self, view, snap, text, x, y, centered=True, bg=False, above=False, vcenter=False, right_align=False):
        layout = view.create_pango_layout(text)
        layout.set_font_description(Pango.FontDescription.from_string('DejaVu Sans 11'))
        tw, th = layout.get_pixel_size()
        px, py = 11, 4
        bw, bh = tw + 2 * px, th + 2 * py
        bx = x - bw / 2.0 if centered else (x - bw if right_align else x)
        by = (y - bh) if above else (y - bh / 2.0 if vcenter else y)
        sw, sh = self.surface_size()
        bx = max(2, min(bx, sw - bw - 2))
        by = max(2, min(by, sh - bh - 2))
        # Tooltips stay on whole pixels while the magnified icons move fractionally.
        # Fractional rounded border/clip intersections produce invalid pixman regions.
        bx, by = round(bx), round(by)
        skip = os.environ.get('MAKOS_DOCK_SKIP', '')
        if bg and 'bg' not in skip:
            rr = Gsk.RoundedRect().init_from_rect(_rect(bx, by, bw, bh), 8)
            if 'clip' not in skip:
                snap.push_rounded_clip(rr)
            if 'grad' not in skip:
                snap.append_linear_gradient(_rect(bx, by, bw, bh), _point(0, by), _point(0, by + bh),
                                            _stops((0, _rgba(.30, .35, .43, .96)), (1, _rgba(.12, .15, .2, .97))))
            if 'clip' not in skip:
                snap.pop()
            if 'border' not in skip:
                snap.append_border(rr, [1] * 4, [_rgba(1, 1, 1, .5)] * 4)
        if 'text' not in skip:
            snap.save()
            snap.translate(_point(bx + px, by + py))
            snap.append_layout(layout, _rgba(1, 1, 1))
            snap.restore()

    def _paint_poofs(self, view, snap, now):
        keep = []
        for (x, y, t0, tex) in self.poofs:
            t = (now - t0) / 0.42
            if t >= 1.0:
                continue
            keep.append((x, y, t0, tex))
            radius_f, alpha, icon_alpha = dm.poof_frame(t)
            size = self.base * 1.15
            if tex is not None and icon_alpha > 0:
                snap.push_opacity(icon_alpha)
                s = size * (1.0 + 0.2 * t)
                snap.append_scaled_texture(tex, Gsk.ScalingFilter.LINEAR, _rect(x - s / 2, y - s / 2, s, s))
                snap.pop()
            for k in range(6):
                ang = k * 1.047 + 0.4
                off = radius_f * size * 0.35
                cx, cy = x + off * math.cos(ang), y + off * math.sin(ang)
                r = size * 0.36 * radius_f
                snap.append_radial_gradient(_rect(cx - r, cy - r, 2 * r, 2 * r), _point(cx, cy), r, r, 0, 1,
                                            _stops((0, _rgba(.95, .97, 1, .75 * alpha)), (.6, _rgba(.8, .86, .94, .45 * alpha)),
                                                   (1, _rgba(.8, .86, .94, 0))))
        self.poofs = keep

    # ------------------------------------------------------------------------------------------ frames
    def _request_frames(self):
        self.view.queue_draw()
        if not self._tick:
            self._last_frame = None
            self._tick = self.view.add_tick_callback(self._on_tick)

    def _animating(self):
        if self.drag or self.poofs or self.bounces or self.anim_start:
            return True
        target = self._strength_target()
        if abs(self.strength - target) > 0.002:
            return True
        if self.strength > 0.002 and self.pointer is not None and abs(self.p_s - self.pointer[0]) > 0.3:
            return True
        want_slide = 0.0 if self.autohide.visible else 1.0
        if abs(self.slide - want_slide) > 0.002:
            return True
        if self.autohide_on or self.fullscreen:
            return True  # delays in the auto-hide state machine run on the frame clock
        return False

    def _strength_target(self):
        if self.pointer is None or self.zoom <= 1.0 or self.drag or self.popover is not None or self.slide > 0.3:
            return 0.0
        return 1.0 if self.pointer[1] <= self.active_v else 0.0

    def _on_tick(self, view, clock):
        now_us = clock.get_frame_time()
        now = now_us / 1e6
        dt = 0.0 if self._last_frame is None else min(0.05, now - self._last_frame)
        if self.record_frames and self._last_frame is not None:
            self.frame_deltas.append((now - self._last_frame) * 1000.0)
        self._last_frame = now
        # pointer follow + magnification strength
        if self.pointer is not None:
            if self.strength < 0.01:
                self.p_s = self.pointer[0]
            else:
                self.p_s = dm.smooth(self.p_s, self.pointer[0], dt, 26.0)
        target = self._strength_target()
        self.strength = dm.smooth(self.strength, target, dt, 16.0)
        if abs(self.strength - target) <= 0.002:
            self.strength = target
        # auto-hide
        vis_before = self.autohide.visible
        popover = self.popover is not None
        dragging = bool(self.drag and self.drag.get('active'))
        until = getattr(self, '_reveal_until', 0)
        inside = self.inside or time.monotonic() < until
        self.autohide.update(time.monotonic(), self.autohide_on, inside, popover, dragging, self.fullscreen)
        if self.autohide.visible != vis_before:
            self._update_region(force=True)
        self.slide = dm.smooth(self.slide, 0.0 if self.autohide.visible else 1.0, dt, 14.0 if not self.reduce else 200.0)
        # slot glide
        if self.anim_start:
            target = self._target_starts()
            for key in list(self.anim_start):
                goal = target.get(key)
                if goal is None:
                    del self.anim_start[key]
                    continue
                self.anim_start[key] = dm.smooth(self.anim_start[key], goal, dt, 22.0)
                if abs(self.anim_start[key] - goal) < 0.4:
                    del self.anim_start[key]
        if self.drag and self.drag.get('active'):
            self._glide_drag_slots(dt)
        self.view.queue_draw()
        if not self._animating():
            self._tick = 0
            self._last_frame = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _target_starts(self):
        n = len(self.items)
        placed = dm.layout(self.lengths, [it.kind != 'separator' for it in self.items], self.p_s, self.strength, self.zoom, origin=self.rest_origin)
        return {self.items[i].key: placed[i].start for i in range(n)}

    def _glide_drag_slots(self, dt):
        """While dragging, neighbours move toward their preview slots instead of jumping."""
        d = self.drag
        order = d['order']
        lens = [lm.item_lengths(self.items, self.base)[i] for i in order]
        slots = dm.rest_layout(lens, origin=self.rest_origin)
        for slot, i in enumerate(order):
            key = self.items[i].key
            goal = slots[slot].start
            cur = self.anim_start.get(key)
            if cur is None:
                cur = self._target_starts().get(key, goal)
            self.anim_start[key] = dm.smooth(cur, goal, dt, 22.0)

    # ------------------------------------------------------------------------------------------ input
    def _controllers(self):
        v = self.view
        motion = Gtk.EventControllerMotion()
        motion.connect('enter', lambda _c, x, y: self._on_motion(x, y, True))
        motion.connect('motion', lambda _c, x, y: self._on_motion(x, y, False))
        motion.connect('leave', lambda _c: self._on_leave())
        v.add_controller(motion)
        drag = Gtk.GestureDrag(button=1)
        drag.connect('drag-begin', self._on_press)
        drag.connect('drag-update', self._on_drag_update)
        drag.connect('drag-end', self._on_release)
        v.add_controller(drag)
        right = Gtk.GestureClick(button=3)
        right.connect('pressed', lambda _g, _n, x, y: self.show_menu(self._index_at(x, y), x, y))
        v.add_controller(right)
        long = Gtk.GestureLongPress(touch_only=True)
        long.connect('pressed', lambda _g, x, y: self.show_menu(self._index_at(x, y), x, y))
        v.add_controller(long)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect('drop', self._on_file_drop)
        v.add_controller(drop)

    def _index_at(self, x, y):
        u, _v = self.uv(x, y)
        i = dm.hit_index(self.displayed(), u)
        if i is not None and self.items[i].kind == 'separator':
            return None
        return i

    def _on_motion(self, x, y, entered):
        u, v = self.uv(x, y)
        if self.pointer is None:
            self.p_s = u
        self.pointer = (u, v)
        if getattr(self, '_leave_id', 0):  # a leave followed by an enter within the grace period is a compositor refocus, not a real exit
            GLib.source_remove(self._leave_id)
            self._leave_id = 0
        was = self.inside
        self.inside = True
        if not was:
            self._update_region(force=True)
        self._request_frames()

    def _on_leave(self):
        if self.drag and self.drag.get('active'):
            return  # the drag grab keeps delivering; leave events are not a cancel
        # Resizing the input region makes the compositor send leave+enter in quick succession. Acting on that leave collapsed the
        # bar, which then re-expanded, and the bar flickered or vanished while hovered. Wait briefly before treating a leave as real.
        if getattr(self, '_leave_id', 0):
            return
        self._leave_id = GLib.timeout_add(LEAVE_GRACE_MS, self._leave_commit)

    def _leave_commit(self):
        self._leave_id = 0
        self.pointer = None
        self.inside = False
        self._update_region(force=True)
        self._request_frames()
        return False

    def _on_press(self, gesture, x, y):
        self.press = (self._index_at(x, y), x, y)

    def _on_drag_update(self, gesture, dx, dy):
        if not self.press:
            return
        index, px, py = self.press
        x, y = px + dx, py + dy
        u, v = self.uv(x, y)
        if self.drag is None:
            if index is None or (dx * dx + dy * dy) < 49:
                return
            item = self.items[index]
            if item.kind not in ('app', 'folder'):
                return
            if item.kind == 'app' and not item.pinned and not item.running:
                return
            self.drag = {'index': index, 'active': True, 'order': list(range(len(self.items))), 'u': u, 'v': v, 'remove': False,
                         'item': item}
            self.pointer = (u, v)
            if self.popover is not None:
                self.popover.popdown()
        d = self.drag
        d['u'], d['v'] = u, v
        self.pointer = (u, v)
        item = d['item']
        d['remove'] = (item.pinned and item.kind in ('app', 'folder')) and dm.drag_off(v - self.shelf_top, 50)
        rng = lm.reorder_range(self.items)
        if item.can_reorder() and rng and not d['remove']:
            rest = dm.rest_layout(lm.item_lengths(self.items, self.base), origin=self.rest_origin)
            target = dm.insertion_index(rest, u, rng[0], rng[1])
            d['order'] = dm.move_item(list(range(len(self.items))), d['index'], target)
            d['target'] = target
        else:
            d['order'] = [i for i in range(len(self.items))]
        self._request_frames()

    def _on_release(self, gesture, dx, dy):
        press, self.press = self.press, None
        if self.drag and self.drag.get('active'):
            self._finish_drag()
            return
        self.drag = None
        if press and press[0] is not None:
            self.activate(press[0])

    def _finish_drag(self):
        d, self.drag = self.drag, None
        item = d['item']
        x, y = self.xy(d['u'], d['v'])
        # items start gliding from where they are drawn to their final slots
        if d.get('remove'):
            tex = self.icons.get(item.icon)
            self.poofs.append((x, y, time.monotonic(), tex))
            if item.kind == 'app':
                self.shell.preferences['pins'] = lm.unpin(self.shell.preferences.get('pins', []), item.key)
            elif item.kind == 'folder':
                self.shell.preferences['launcher_folders'] = [f for f in self.shell.preferences.get('launcher_folders', lm.DEFAULT_FOLDERS)
                                                              if f != item.key]
            self._save()
            self.rebuild_items()
        elif item.can_reorder() and 'target' in d:
            pinned_before = [i.key for i in self.items if i.can_reorder()]
            rng = lm.reorder_range(self.items)
            new_index = d['target'] - rng[0]
            if pinned_before.index(item.key) != new_index:
                self.shell.preferences['pins'] = lm.reorder(self.shell.preferences.get('pins', []), item.key, new_index)
                self._save()
                self.rebuild_items()
        self.pointer = None if not self.inside else self.pointer
        self._request_frames()

    def _save(self):
        try:
            common.save_settings(self.shell.preferences)
        except OSError as error:
            print('launcher settings not saved:', error, flush=True)

    def _on_file_drop(self, _target, value, x, y):
        index = self._index_at(x, y)
        if index is None or self.items[index].kind != 'app':
            return False
        item = self.items[index]
        try:
            files = [f.get_path() for f in value.get_files() if f.get_path()]
        except AttributeError:
            return False
        for path in files[:20]:
            self.shell.launch_with(item.key, path)
        return bool(files)

    # ------------------------------------------------------------------------------------------ actions
    def activate(self, index):
        item = self.items[index]
        if item.kind == 'app':
            if item.windows:
                self.shell.bridge.command('activate', item.windows[0]['id'])
                badge_mod.default.clear(item.key)
            else:
                self.start_bounce(item.key)
                self.shell.launch(item.key)
        elif item.kind == 'window':
            self._restore_target(item)
            self.shell.bridge.command('activate', item.key)
        elif item.kind == 'folder':
            self.show_stack(index)
        elif item.kind == 'trash':
            self.shell.launch(lm.TRASH)

    def _restore_target(self, item):
        """Tell the minimize effect where the window comes back from (the item's slot)."""
        hook = getattr(self.shell, 'genie', None)
        if hook:
            hook.aim_at(self, item)

    def run_action(self, item, key):
        sh = self.shell
        if key == 'open':
            if item.kind == 'folder':
                sh.launch_with('files', item.path)
            else:
                self.activate(self.items.index(item)) if item in self.items else sh.launch(item.key)
        elif key == 'keep':
            sh.preferences['pins'] = lm.pin(sh.preferences.get('pins', []), item.key)
            self._save()
            self.rebuild_items()
        elif key == 'remove':
            sh.preferences['pins'] = lm.unpin(sh.preferences.get('pins', []), item.key)
            self._save()
            self.rebuild_items()
        elif key == 'remove-folder':
            sh.preferences['launcher_folders'] = [f for f in sh.preferences.get('launcher_folders', lm.DEFAULT_FOLDERS) if f != item.key]
            self._save()
            self.rebuild_items()
        elif key == 'show':
            target = item.path
            if not target:
                info = None
                try:
                    info = Gio.DesktopAppInfo.new(item.key + '.desktop')
                except TypeError:
                    pass
                target = str(Path(info.get_filename()).parent) if info and info.get_filename() else str(Path.home())
            sh.launch_with('files', target)
        elif key == 'quit':
            for w in item.windows:
                sh.bridge.command('close', w['id'])
        elif key == 'hide':
            for w in item.windows:
                sh.bridge.command('minimize', w['id'])
        elif key == 'restore':
            sh.bridge.command('activate', item.key)
        elif key == 'close':
            sh.bridge.command('close', item.key)
        elif key.startswith('view-'):
            views = dict(sh.preferences.get('folder_views', {}))
            views[item.key] = key[5:]
            sh.preferences['folder_views'] = views
            self._save()
        elif key == 'sort':
            pass

    # ------------------------------------------------------------------------------------------ popovers
    def _open_popover(self, item, rect, build, side=None):
        self.close_popover()
        pop = Gtk.Popover()
        pop.set_parent(self.view)
        pop.set_autohide(True)
        pop.set_has_arrow(False)
        side = side or {'bottom': Gtk.PositionType.TOP, 'left': Gtk.PositionType.RIGHT, 'right': Gtk.PositionType.LEFT}[self.pos]
        pop.set_position(side)
        x, y, w, h = rect
        r = Gdk.Rectangle()
        r.x, r.y, r.width, r.height = int(x), int(y), int(w), int(h)
        pop.set_pointing_to(r)
        col = ui.box(True, 2)
        build(col, pop)
        pop.set_child(col)
        self.popover, self.popover_item = pop, item

        def closed(_p):
            if self.popover is pop:
                self.popover = None
                self.popover_item = None
            GLib.idle_add(lambda: (pop.unparent(), False)[1])
            self._request_frames()
        pop.connect('closed', closed)
        self._request_frames()
        pop.popup()
        return pop

    def close_popover(self):
        if self.popover is not None:
            self.popover.popdown()

    def show_menu(self, index, x=0, y=0):
        if index is None:
            return
        item = self.items[index]
        actions = lm.context_actions(item, len(item.windows))
        rect = self.item_rect(index)

        def build(col, pop):
            col.set_size_request(220, -1)
            col.append(Gtk.Label(label=item.name, css_classes=['title-label'], margin_top=4, margin_bottom=4))
            if item.kind == 'app' and item.windows:
                for w in item.windows[:12]:
                    col.append(self._menu_button(pop, ('• ' if not w.get('minimized') else '◦ ') + str(w.get('caption', ''))[:40],
                                                 lambda w=w: self.shell.bridge.command('activate', w['id'])))
                col.append(Gtk.Separator())
            last_sep = True
            for key, label in actions:
                if key == '-':
                    if not last_sep:
                        col.append(Gtk.Separator())
                    last_sep = True
                    continue
                last_sep = False
                if key in ('keep', 'remove') and item.kind == 'app' and item.key == lm.TRASH:
                    continue
                col.append(self._menu_button(pop, label, lambda k=key: self.run_action(item, k)))
        self._open_popover(item, rect, build)

    def _menu_button(self, pop, label, fn):
        def go():
            pop.popdown()
            GLib.idle_add(lambda: (fn(), False)[1])
        b = ui.button(label, go)
        b.set_halign(Gtk.Align.FILL)
        return b

    def show_stack(self, index):
        item = self.items[index]
        entries = lm.list_folder(item.path, 40)
        mode = dm.stack_view(self.shell.preferences.get('folder_views', {}).get(item.key, 'auto'), len(entries))
        rect = self.item_rect(index)

        def open_entry(name, is_dir):
            full = str(Path(item.path) / name)
            self.shell.open_path(full)

        def build(col, pop):
            if not entries:
                col.append(Gtk.Label(label='This folder is empty', margin_top=14, margin_bottom=14, margin_start=18, margin_end=18))
            elif mode == 'fan':
                self._build_fan(col, pop, entries, open_entry)
            else:
                self._build_grid(col, pop, entries, open_entry)
            col.append(self._menu_button(pop, 'Open in Files', lambda: self.shell.launch_with('files', item.path)))
        self._open_popover(item, rect, build)

    def _tile(self, pop, name, is_dir, open_entry, size=44):
        box = ui.box(True, 2)
        box.append(ui.icon(lm.file_icon(name, is_dir), size))
        label = Gtk.Label(label=name, max_width_chars=14, ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=['stack-label'])
        box.append(label)
        b = Gtk.Button(css_classes=['file-tile'])
        b.set_child(box)
        b.set_tooltip_text(name)

        def go(*_):
            pop.popdown()
            GLib.idle_add(lambda: (open_entry(name, is_dir), False)[1])
        b.connect('clicked', go)
        return b

    def _build_grid(self, col, pop, entries, open_entry):
        cols, rows = dm.grid_dims(len(entries))
        grid = Gtk.Grid(column_spacing=4, row_spacing=4, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        for n, (name, is_dir) in enumerate(entries):
            grid.attach(self._tile(pop, name, is_dir, open_entry), n % cols, n // cols, 1, 1)
        scroller = Gtk.ScrolledWindow(propagate_natural_width=True, propagate_natural_height=True, max_content_height=440,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(grid)
        col.append(scroller)

    def _build_fan(self, col, pop, entries, open_entry):
        entries = entries[:10]
        spacing = 46
        bend = {'bottom': 1.0, 'left': 0.0, 'right': 0.0}[self.pos]
        pos = dm.fan_positions(len(entries), spacing, bend)
        fixed = Gtk.Fixed()
        width = 230 + int(max((p[0] for p in pos), default=0))
        height = len(entries) * spacing + 10
        fixed.set_size_request(width, height)
        for n, ((name, is_dir), (dx, dy)) in enumerate(zip(entries, pos)):
            row = ui.box(spacing=10)
            row.append(ui.icon(lm.file_icon(name, is_dir), 36))
            row.append(Gtk.Label(label=name, max_width_chars=22, ellipsize=Pango.EllipsizeMode.MIDDLE, xalign=0))
            b = Gtk.Button(css_classes=['file-tile'])
            b.set_child(row)

            def go(*_, name=name, is_dir=is_dir):
                pop.popdown()
                GLib.idle_add(lambda: (open_entry(name, is_dir), False)[1])
            b.connect('clicked', go)
            # nearest-to-the-bar item at the bottom of the fan
            fixed.put(b, dx, height - spacing - dy - 4)
        col.append(fixed)

    # ------------------------------------------------------------------------------------------ input region
    def _update_region(self, force=False):
        """Clicks pass through everywhere except the bar: a thin strip when idle, the magnified area while the pointer is on
        it, only the 3 px hot edge while auto-hidden."""
        if os.environ.get('MAKOS_DEBUG_DOCK'):
            print('DOCK_UPDATE_REGION', cairo is not None, self.window.get_surface(), flush=True)
        if cairo is None:
            return
        surf = self.window.get_surface()
        if surf is None:
            return
        w, h = self.surface_size()
        hidden = not self.autohide.visible and (self.autohide_on or self.fullscreen)
        if hidden:
            depth = 3
        elif self.inside or self.popover is not None or (self.drag and self.drag.get('active')):
            depth = self.active_v + (self.bounce_h if self.bounces else 0)
        else:
            depth = self.reserve
        state = (w, h, int(depth), self.pos)
        if state == self._region_state and not force:
            return
        self._region_state = state
        depth = int(depth)
        if self.pos == 'bottom':
            rect = cairo.RectangleInt(0, max(0, h - depth), w, min(depth, h))
        elif self.pos == 'left':
            rect = cairo.RectangleInt(0, 0, min(depth, w), h)
        else:
            rect = cairo.RectangleInt(max(0, w - depth), 0, min(depth, w), h)
        if os.environ.get('MAKOS_DEBUG_DOCK'):
            print('DOCK_REGION', self.pos, (rect.x, rect.y, rect.width, rect.height), 'surface', (w, h), flush=True)
        if os.environ.get('MAKOS_DOCK_NOREGION'):
            return
        surf.set_input_region(cairo.Region(rect))

    # ------------------------------------------------------------------------------------------ test hooks
    def sim_pointer(self, u, v=None):
        """Pretend the pointer is over rest coordinate u (rig/test use)."""
        v = self.v0 + self.base / 2.0 if v is None else v
        x, y = self.xy(u, v)
        self._on_motion(x, y, True)

    def sim_leave(self):
        self._on_leave()


