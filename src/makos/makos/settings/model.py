"""Validation of the MakkOS settings.json keys owned by the Settings panes. Pure Python (no GTK, no I/O).

`clean(data)` repairs a loaded settings dict in place: unknown or invalid values fall back to defaults, so a hand-edited
or corrupt file can never crash the shell.
"""
import re

ACCENTS = ('blossom', 'blue', 'graphite', 'teal', 'green', 'orange', 'red', 'purple')
SCROLLBARS = ('auto', 'always')
CORNER_NAMES = ('top_left', 'top_right', 'bottom_left', 'bottom_right')
# Hot-corner actions understood by bridge/bridge.js (script edges); Spread, Desks and Seek go to the shell.
CORNER_ACTIONS = ('none', 'show_desktop', 'lock_screen', 'spread', 'desks', 'seek')
SEARCH_ENGINES = ('duckduckgo', 'startpage', 'wikipedia')
MAX_REPLACEMENTS = 200


def _int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _float(value, lo, hi, default):
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def clean_replacements(items):
    """[[from, to], ...] with sane lengths; duplicates by trigger keep the last entry."""
    out = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(x, str) for x in item):
            src, dst = item[0].strip(), item[1]
            if 1 <= len(src) <= 40 and ' ' not in src and 0 < len(dst) <= 400:
                out[src] = dst
        if len(out) >= MAX_REPLACEMENTS:
            break
    return [[k, v] for k, v in out.items()]


def clean(data):
    if data.get('accent') not in ACCENTS:
        data['accent'] = 'graphite' if data.get('graphite') is True else 'blue'
    data['graphite'] = data['accent'] == 'graphite'
    data['font_size'] = _int(data.get('font_size'), 10, 18, 12)
    if data.get('scrollbars') not in SCROLLBARS:
        data['scrollbars'] = 'auto'
    for key in ('reduce_transparency', 'launcher_magnify', 'launcher_recents', 'clock_24h', 'high_contrast', 'privacy_indicators'):
        data[key] = bool(data.get(key))
    data['launcher_magnify_percent'] = _int(data.get('launcher_magnify_percent'), 0, 100, 55)
    data['text_scale'] = _float(data.get('text_scale'), 1.0, 2.0, 1.0)
    wp = data.get('wallpaper')
    data['wallpaper'] = wp if isinstance(wp, str) and len(wp) < 4096 else ''
    corners = data.get('hot_corners')
    data['hot_corners'] = {k: v for k, v in (corners or {}).items()
                           if k in CORNER_NAMES and v in CORNER_ACTIONS} if isinstance(corners, dict) else {}
    data['text_replacements'] = clean_replacements(data.get('text_replacements'))
    ex = data.get('seek_exclusions')
    data['seek_exclusions'] = [x for x in ex if isinstance(x, str) and x.startswith('/') and len(x) < 4096][:200] if isinstance(ex, list) else []
    if data.get('seek_web_engine') not in SEARCH_ENGINES:
        data['seek_web_engine'] = 'duckduckgo'
    return data


# ---------------------------------------------------------------- appearance CSS (loaded after glass.css by ui.install_theme)
# name -> (light, mid, dark, border): original gel colour stops; makos.appearance builds the widget theme from these.
ACCENT_COLORS = {
    'blossom': ('#ffe0eb', '#ff8cb4', '#ff0058', '#bd0041'),
    'blue': ('#d7efff', '#8cc7ff', '#418ee6', '#3873b1'),
    'graphite': ('#e7e9ec', '#bfc4ca', '#7b838d', '#5d646d'),
    'teal': ('#d4f6f1', '#86ddd0', '#2fa597', '#2a8379'),
    'green': ('#dff5d4', '#9be07f', '#4fae33', '#3f8a2a'),
    'orange': ('#ffe9d0', '#ffbf7a', '#ee8a1c', '#b86a12'),
    'red': ('#ffdcd6', '#ff9d90', '#e0483a', '#a8382d'),
    'purple': ('#eadcff', '#c3a2f5', '#8a55d6', '#6c42a8'),
}
# Styles for the Settings window itself (kept here so the theme engineer's glass.css stays untouched).
STATIC = ('.settings-group { padding: 4px 0 8px 0; } .settings-status { color: #3b5b7d; font-size: 11px; padding: 4px 0; } '
          '.settings-status.error { color: #a02a1f; } .hint-card { background: alpha(#fff,.55); border: 1px solid alpha(#7d8fa3,.5); '
          'border-radius: 7px; padding: 10px 12px; } .seek-row { padding: 4px 8px; border-radius: 5px; } '
          '.seek-row.selected { background: linear-gradient(#63a7ef,#2d70c8); } .seek-row.selected label { color: #fff; } '
          '.seek-group { color: #66778b; font-size: 10px; font-weight: bold; padding: 8px 8px 2px 8px; } '
          '.seek-bar-field { min-height: 20px; margin: 3px 0 3px 8px; }')
# classes with their own pixel size in glass.css: scaled together with the base size
SIZED_CLASSES = {'.hero': 30, '.subtitle': 12, '.section-title': 11, '.statusbar': 11, '.source-heading': 10, '.settings-status': 11, '.seek-group': 10}
_HEX = re.compile(r'^#[0-9a-f]{6}$')


def css(data):
    """Override stylesheet for font size/scale, contrast and transparency (accent/Graphite live in makos.appearance)."""
    clean(data)
    k = data['font_size'] * data['text_scale'] / 12
    out = [STATIC]
    if abs(k - 1) > 0.001:
        out.append('* { font-size: %.1fpx; }' % (12 * k))
        out += ['%s { font-size: %.1fpx; }' % (cls, px * k) for cls, px in SIZED_CLASSES.items()]
    if data['reduce_transparency']:
        out.append('.menu-bar { background: #eef1f5; } .launcher-shelf { background: #aeb9c8; } '
                   '.overview { background: #152538; } popover contents { background: #fafcfe; } .seek-sheet { background: #f2f5f9; }')
    if data['high_contrast']:
        out.append('window { color: #000; background: #fff; } button, entry { border: 2px solid #000; } '
                   '.subtitle, .section-title, .statusbar, .source-heading { color: #000; } '
                   'button:focus-visible, entry:focus { outline: 3px solid #000; }')
    return '\n'.join(out) + '\n'
