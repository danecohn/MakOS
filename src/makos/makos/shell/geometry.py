"""Window geometry rules: Spread layout, Desks thumbnails, snapping, zoom, per-app memory. Pure Python (no GTK)."""
import math
from collections import namedtuple

Rect = namedtuple('Rect', 'x y w h')


def fit(w, h, bw, bh, max_scale=1.0):
    """Scale (w, h) to fit inside (bw, bh) keeping the aspect ratio; returns (width, height, scale)."""
    if w <= 0 or h <= 0:
        return (0.0, 0.0, 0.0)
    s = min(bw / w, bh / h, max_scale)
    return (w * s, h * s, s)


def spread_layout(sizes, area, gap=28.0, max_scale=0.95):
    """Place windows (list of (w, h)) in the free area as a centred grid of the largest uniform-ish thumbnails.

    Tries every row count, keeps the arrangement whose smallest thumbnail scale is largest, and centres each row.
    Returns a list of Rect (same order as `sizes`) in the coordinates of `area` (a Rect)."""
    n = len(sizes)
    if n == 0:
        return []
    best, best_score = None, -1.0
    for rows in range(1, n + 1):
        cols = math.ceil(n / rows)
        cw = (area.w - gap * (cols - 1)) / cols
        ch = (area.h - gap * (rows - 1)) / rows
        if cw <= 8 or ch <= 8:
            continue
        scales = [fit(w, h, cw, ch, max_scale)[2] for (w, h) in sizes]
        score = min(scales) + 0.0001 * sum(scales)
        if score > best_score:
            best_score, best = score, (rows, cols, cw, ch)
    if best is None:
        rows, cols = n, 1
        cw, ch = area.w, max(8.0, (area.h - gap * (n - 1)) / n)
    else:
        rows, cols, cw, ch = best
    out = []
    for r in range(rows):
        row = list(range(r * cols, min(n, (r + 1) * cols)))
        fitted = [fit(sizes[i][0], sizes[i][1], cw, ch, max_scale) for i in row]
        row_width = sum(f[0] for f in fitted) + gap * (len(row) - 1)
        x = area.x + (area.w - row_width) / 2.0
        for i, (fw, fh, _s) in zip(row, fitted):
            yy = area.y + r * (ch + gap) + (ch - fh) / 2.0
            out.append((i, Rect(x, yy, fw, fh)))
            x += fw + gap
    out.sort()
    return [r for _, r in out]


def hit_rect(rects, x, y):
    for i, r in enumerate(rects):
        if r.x <= x <= r.x + r.w and r.y <= y <= r.y + r.h:
            return i
    return None


def navigate(rects, current, direction):
    """Keyboard navigation in a grid of rects: nearest rect in the given direction ('left','right','up','down')."""
    if not rects:
        return None
    if current is None:
        return 0
    cur = rects[current]
    cx, cy = cur.x + cur.w / 2.0, cur.y + cur.h / 2.0
    best, best_d = None, None
    for i, r in enumerate(rects):
        if i == current:
            continue
        rx, ry = r.x + r.w / 2.0, r.y + r.h / 2.0
        dx, dy = rx - cx, ry - cy
        along, across = {'left': (-dx, abs(dy)), 'right': (dx, abs(dy)), 'up': (-dy, abs(dx)), 'down': (dy, abs(dx))}[direction]
        if along <= 1:
            continue
        d = along + 2.0 * across
        if best_d is None or d < best_d:
            best, best_d = i, d
    return current if best is None else best


def desk_thumb(window, screen, thumb):
    """Rectangle of a window inside a desk thumbnail. `window`/`screen` are Rect in screen pixels, `thumb` is a Rect."""
    sx, sy = thumb.w / screen.w, thumb.h / screen.h
    return Rect(thumb.x + (window.x - screen.x) * sx, thumb.y + (window.y - screen.y) * sy,
                max(2.0, window.w * sx), max(2.0, window.h * sy))


def strip_layout(count, area, ratio, gap=18.0, max_w=320.0):
    """Desk thumbnails side by side, centred; `ratio` = screen width / height. Returns list of Rect."""
    if count <= 0:
        return []
    w = min(max_w, (area.w - gap * (count - 1)) / count)
    h = w / ratio
    if h > area.h:
        h = area.h
        w = h * ratio
    total = w * count + gap * (count - 1)
    x = area.x + (area.w - total) / 2.0
    return [Rect(x + i * (w + gap), area.y + (area.h - h) / 2.0, w, h) for i in range(count)]


# ----------------------------------------------------------------------------------------------- snapping
def snap_zone(x, y, area, edge=14, corner=90):
    """Snap zone for a pointer at (x, y) inside `area`: 'left','right','top'(maximize), corners 'tl','tr','bl','br', or None."""
    left, right = x <= area.x + edge, x >= area.x + area.w - edge
    top, bottom = y <= area.y + edge, y >= area.y + area.h - edge
    near_y_top = y <= area.y + corner
    near_y_bottom = y >= area.y + area.h - corner
    if left and near_y_top:
        return 'tl'
    if right and near_y_top:
        return 'tr'
    if left and near_y_bottom:
        return 'bl'
    if right and near_y_bottom:
        return 'br'
    if left:
        return 'left'
    if right:
        return 'right'
    if top:
        return 'top'
    return None


def snap_rect(zone, area):
    """Rect a window takes in a snap zone."""
    hw, hh = area.w / 2.0, area.h / 2.0
    return {
        'left': Rect(area.x, area.y, hw, area.h), 'right': Rect(area.x + hw, area.y, hw, area.h),
        'top': Rect(*area), 'tl': Rect(area.x, area.y, hw, hh), 'tr': Rect(area.x + hw, area.y, hw, hh),
        'bl': Rect(area.x, area.y + hh, hw, hh), 'br': Rect(area.x + hw, area.y + hh, hw, hh),
    }.get(zone)


def zoom_target(geom, area, saved=None, margin=0.0):
    """The Zoom button: a window that fills the work area returns to its saved size; anything else grows to fill it
    (leaving `margin`). `saved` is the geometry remembered before the last zoom. Returns (Rect, 'zoomed'|'restored')."""
    full = Rect(area.x + margin, area.y + margin, area.w - 2 * margin, area.h - 2 * margin)
    near = (abs(geom.x - full.x) <= 4 and abs(geom.y - full.y) <= 4 and abs(geom.w - full.w) <= 8 and abs(geom.h - full.h) <= 8)
    if near:
        if saved and not (abs(saved.w - full.w) <= 8 and abs(saved.h - full.h) <= 8):
            return (saved, 'restored')
        return (Rect(area.x + area.w * 0.12, area.y + area.h * 0.1, area.w * 0.76, area.h * 0.8), 'restored')
    return (full, 'zoomed')


def clamp_to_area(geom, area, min_visible=80):
    """Keep a remembered geometry on screen (monitors change): shrink to the area and keep at least `min_visible` px of
    the window inside it."""
    w = min(geom.w, area.w)
    h = min(geom.h, area.h)
    x = max(area.x - w + min_visible, min(geom.x, area.x + area.w - min_visible))
    y = max(area.y, min(geom.y, area.y + area.h - min_visible))
    return Rect(x, y, w, h)


def geometry_from(d):
    return Rect(float(d.get('x', 0)), float(d.get('y', 0)), float(d.get('w', 0)), float(d.get('h', 0)))


def clean_memory(raw, limit=200):
    """Validate per-application window memory read from disk: {class: {'x','y','w','h'}}."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, g in raw.items():
        if not isinstance(key, str) or not isinstance(g, dict) or len(key) > 120:
            continue
        try:
            vals = {k: int(g[k]) for k in ('x', 'y', 'w', 'h')}
        except (KeyError, TypeError, ValueError):
            continue
        if vals['w'] < 120 or vals['h'] < 80 or vals['w'] > 16000 or vals['h'] > 16000 or abs(vals['x']) > 40000 or abs(vals['y']) > 40000:
            continue
        out[key.lower()] = vals
        if len(out) >= limit:
            break
    return out
