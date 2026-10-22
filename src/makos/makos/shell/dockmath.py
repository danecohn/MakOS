"""Launcher Bar maths: magnification, layout, hit testing, reordering, bounce, stack fans, auto-hide. Pure Python.

No GTK import so every rule can be unit tested. Coordinates are along the bar's main axis (u): horizontal for a bottom
bar, vertical for left/right bars. `v` is the distance from the screen edge into the screen.
"""
import math
from collections import namedtuple

Placement = namedtuple('Placement', 'start length')

GAP = 6.0          # space between neighbouring rest-size items
PAD = 14.0         # shelf padding before the first / after the last item
SIGMA_ITEMS = 1.25  # Gaussian width, in item pitches


def gauss(distance, sigma):
    return math.exp(-(distance * distance) / (2.0 * sigma * sigma))


def zoom_factor(percent):
    """Settings store the extra magnification in percent (0..100); 55 means icons grow to 1.55x."""
    return 1.0 + max(0, min(100, float(percent))) / 100.0


def rest_layout(lengths, gap=GAP, origin=0.0):
    """Placements with no magnification. `lengths` is the rest length of every item."""
    out, pos = [], origin
    for n in lengths:
        out.append(Placement(pos, float(n)))
        pos += n + gap
    return out


def rest_total(lengths, gap=GAP):
    return sum(lengths) + gap * max(0, len(lengths) - 1)


def layout(lengths, magnifiable, pointer, strength, zoom, gap=GAP, origin=0.0, anchor=True):
    """Gaussian magnification. `pointer` is measured in rest coordinates (the same frame rest_layout uses).

    Every item grows by 1 + (zoom-1)*strength*gauss(distance from pointer to its rest centre); items are packed with
    the usual gap, centred on the rest layout, then shifted so the point under the pointer stays under it (the icon you
    aim at does not run away from the cursor). Returns a list of Placement in the same frame.
    """
    rest = rest_layout(lengths, gap, origin)
    if not lengths:
        return []
    if strength <= 0 or zoom <= 1.0 or pointer is None:
        return rest
    pitch = (sum(lengths) / len(lengths)) + gap
    sigma = SIGMA_ITEMS * pitch
    sizes = []
    for p, can in zip(rest, magnifiable):
        if can:
            sizes.append(p.length * (1.0 + (zoom - 1.0) * strength * gauss(p.start + p.length / 2.0 - pointer, sigma)))
        else:
            sizes.append(p.length)
    total = sum(sizes) + gap * (len(sizes) - 1)
    base_total = rest_total(lengths, gap)
    start = origin - (total - base_total) / 2.0
    placed, pos = [], start
    for s in sizes:
        placed.append(Placement(pos, s))
        pos += s + gap
    if anchor:
        shift = pointer - _displayed_position(rest, placed, pointer)
        limit = (total - base_total) / 2.0
        shift = max(-limit, min(limit, shift))
        placed = [Placement(p.start + shift, p.length) for p in placed]
    return placed


def _displayed_position(rest, placed, u):
    """Where rest coordinate `u` ends up in the magnified layout (piecewise linear through the item bodies)."""
    for r, p in zip(rest, placed):
        if r.start <= u <= r.start + r.length:
            t = (u - r.start) / r.length if r.length else 0.0
            return p.start + t * p.length
    if u < rest[0].start:
        return placed[0].start + (u - rest[0].start)
    if u > rest[-1].start + rest[-1].length:
        return placed[-1].start + placed[-1].length + (u - rest[-1].start - rest[-1].length)
    # in a gap between two items
    for i in range(len(rest) - 1):
        a, b = rest[i], rest[i + 1]
        if a.start + a.length <= u <= b.start:
            span = b.start - (a.start + a.length)
            t = (u - (a.start + a.length)) / span if span else 0.0
            pa, pb = placed[i], placed[i + 1]
            return pa.start + pa.length + t * (pb.start - pa.start - pa.length)
    return u


def max_growth(lengths, zoom, gap=GAP):
    """Largest extra length the magnified bar can have over the rest bar (used to size the layer surface)."""
    if not lengths or zoom <= 1.0:
        return 0.0
    magn = [True] * len(lengths)
    base = rest_total(lengths, gap)
    rest = rest_layout(lengths, gap)
    best = 0.0
    for r in rest:
        placed = layout(lengths, magn, r.start + r.length / 2.0, 1.0, zoom, gap)
        best = max(best, placed[-1].start + placed[-1].length - placed[0].start - base)
    return best


def max_item_length(length, zoom):
    return length * max(1.0, zoom)


def hit_index(placements, u, gap=GAP):
    """Index of the item whose slot (extended by half a gap on each side) contains `u`, or None."""
    for i, p in enumerate(placements):
        if p.start - gap / 2.0 <= u <= p.start + p.length + gap / 2.0:
            return i
    return None


def insertion_index(rest, dragged_centre, lo, hi):
    """Target slot for a dragged item. `rest` are the rest placements, `lo`..`hi` the (inclusive) index range in which
    reordering is allowed (e.g. the pinned apps). Returns an index in lo..hi."""
    best, dist = lo, None
    for i in range(lo, hi + 1):
        d = abs(rest[i].start + rest[i].length / 2.0 - dragged_centre)
        if dist is None or d < dist:
            best, dist = i, d
    return best


def move_item(seq, src, dst):
    """Return a copy of `seq` with the element at src moved to index dst."""
    seq = list(seq)
    if not (0 <= src < len(seq)) or not (0 <= dst < len(seq)):
        return seq
    item = seq.pop(src)
    seq.insert(dst, item)
    return seq


def drag_off(offset, threshold):
    """True when a drag has left the bar sideways far enough that releasing removes the item. `offset` is the pointer's
    distance from the bar's shelf, measured away from the screen edge (negative: toward the edge)."""
    return offset > threshold


# ----------------------------------------------------------------------------------------------------- animation
def bounce_offset(t, height, period=0.5):
    """Height of a launching icon `t` seconds after launch: repeated hops with a slightly shrinking apex."""
    if t < 0:
        return 0.0
    n = int(t / period)
    phase = (t % period) / period
    return height * (0.88 ** n) * 4.0 * phase * (1.0 - phase)


def smooth(current, target, dt, rate=18.0):
    """Frame-rate independent exponential smoothing."""
    if dt <= 0:
        return current
    k = 1.0 - math.exp(-rate * dt)
    return current + (target - current) * k


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def poof_frame(t):
    """Poof of smoke on removal: (puff radius factor, alpha, icon alpha) at progress t in 0..1."""
    t = max(0.0, min(1.0, t))
    return (0.3 + 1.1 * ease_out_cubic(t), (1.0 - t) ** 1.5, max(0.0, 1.0 - t * 3.0))


# ----------------------------------------------------------------------------------------------------- stacks
def grid_dims(n, max_cols=5):
    if n <= 0:
        return (0, 0)
    cols = min(max_cols, max(1, math.ceil(math.sqrt(n))))
    return cols, math.ceil(n / cols)


def fan_positions(n, spacing, bend=0.0):
    """Item i (0 = nearest the bar) of a fan: (along the bar, away from the bar). The fan curves with the square of
    the index and `bend` (+1 curves toward the end of the bar, -1 the other way)."""
    return [(bend * 0.045 * spacing * i * i, i * spacing) for i in range(n)]


def stack_view(mode, n, grid_threshold=8):
    """'fan' or 'grid' for a stack. 'auto' fans up to `grid_threshold` items (a fan of many items leaves the screen)."""
    if mode in ('fan', 'grid'):
        return mode
    return 'fan' if n <= grid_threshold else 'grid'


# ----------------------------------------------------------------------------------------------------- auto-hide
class AutoHide:
    """Decides whether the bar is shown. Call update() each frame (or on every state change).

    * not auto-hide, no full screen app: always shown.
    * popover/menu open or an item being dragged: stays as it is (never hides under a menu).
    * pointer on the bar or on the screen edge for `show_delay`: shown.
    * pointer left for `hide_delay`: hidden.
    * a full screen app is active: hidden and only revealed after the pointer rested on the edge for `fs_dwell`,
      so a stray flick at the edge in a game or video does not pop the bar over it.
    """

    def __init__(self, show_delay=0.12, hide_delay=0.45, fs_dwell=0.45):
        self.show_delay, self.hide_delay, self.fs_dwell = show_delay, hide_delay, fs_dwell
        self.visible = True
        self._edge_since = None
        self._left_since = None

    def update(self, now, autohide, inside, popover=False, dragging=False, fullscreen=False):
        if not autohide and not fullscreen:
            self.visible = True
            self._edge_since = self._left_since = None
            return True
        if popover or dragging:
            self._left_since = None
            return self.visible
        if inside:
            self._left_since = None
            if self._edge_since is None:
                self._edge_since = now
            need = self.fs_dwell if fullscreen else self.show_delay
            if self.visible or now - self._edge_since >= need:
                self.visible = True
        else:
            self._edge_since = None
            if self.visible:
                if self._left_since is None:
                    self._left_since = now
                if now - self._left_since >= self.hide_delay:
                    self.visible = False
                    self._left_since = None
        return self.visible

    def force(self, visible):
        self.visible = bool(visible)
        self._edge_since = self._left_since = None


# ----------------------------------------------------------------------------------------------------- orientation
def to_xy(position, u, v, width, height):
    """Map bar coordinates (u along the bar, v away from the screen edge) to surface x, y for the bar position."""
    if position == 'left':
        return (v, u)
    if position == 'right':
        return (width - v, u)
    return (u, height - v)
