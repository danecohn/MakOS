"""Desks & Spread backend: desk count (KWin VirtualDesktopManager, persisted in the compositor's kwinrc) and hot corners.

Hot corners are stored in the compositor config as [Script-makos-bridge] keys that bridge/bridge.js reads with readConfig()
when the script (re)loads; `reload_bridge()` asks KWin to unload and load it again so the change is live.
"""
import re

from .. import common
from ..settings import model
from . import look, sysutil

KWIN = 'org.kde.KWin'
VDM = '/VirtualDesktopManager'
VDM_IFACE = 'org.kde.KWin.VirtualDesktopManager'
MIN_DESKS, MAX_DESKS = 1, 12
CORNER_LABELS = [('top_left', 'Top left'), ('top_right', 'Top right'), ('bottom_left', 'Bottom left'), ('bottom_right', 'Bottom right')]
# Actions understood by bridge.js: shell-owned ones go through org.makos.Control.Action.
CORNER_ACTIONS = [('none', 'No action'), ('show_desktop', 'Show the desktop'), ('lock_screen', 'Lock the screen'),
                  ('spread', 'Spread'), ('desks', 'Desks'), ('seek', 'Seek')]
CORNER_ACTION_KEYS = [a for a, _t in CORNER_ACTIONS]
BRIDGE_PLUGIN = 'makos-bridge'


def desktops():
    """[(id, name)] in order, from KWin; [] when KWin is not reachable."""
    res = sysutil.run(['busctl', '--user', 'get-property', KWIN, VDM, VDM_IFACE, 'desktops'])
    if res.code != 0:
        return []
    return [(m[0], m[1]) for m in re.findall(r'"([0-9a-fA-F-]{8,})"\s+"([^"]*)"', res.out)]


def count():
    d = desktops()
    if d:
        return len(d)
    try:
        return int(sysutil.kread('kwinrc', 'Desktops', 'Number', '4') or 4)
    except ValueError:
        return 4


def set_count(n):
    n = int(n)
    if not MIN_DESKS <= n <= MAX_DESKS:
        raise ValueError(f'Use between {MIN_DESKS} and {MAX_DESKS} desks.')
    sysutil.kwrite('kwinrc', 'Desktops', 'Number', n)
    sysutil.kwrite('kwinrc', 'Desktops', 'Rows', 1)
    live = desktops()
    ok = True
    if live:
        for i in range(len(live), n):
            ok = sysutil.run(['busctl', '--user', 'call', KWIN, VDM, VDM_IFACE, 'createDesktop', 'us', str(i), f'Desk {i + 1}']).code == 0 and ok
        for ident, _name in live[n:][::-1]:
            ok = sysutil.run(['busctl', '--user', 'call', KWIN, VDM, VDM_IFACE, 'removeDesktop', 's', ident]).code == 0 and ok
    else:
        sysutil.kwin_reconfigure()
    return {'count': n, 'live': bool(live), 'ok': ok}


def hot_corners():
    return {k: v for k, v in {**{c: 'none' for c, _t in CORNER_LABELS}, **common.load_settings()['hot_corners']}.items()}


def set_hot_corner(corner, action):
    if corner not in model.CORNER_NAMES:
        raise ValueError('Unknown corner.')
    if action not in CORNER_ACTION_KEYS:
        raise ValueError('Unknown corner action.')
    data = common.load_settings()
    corners = dict(data['hot_corners'])
    corners[corner] = action
    data['hot_corners'] = corners
    common.save_settings(data)
    key = 'Hot' + ''.join(p.capitalize() for p in corner.split('_'))
    sysutil.kwrite('kwinrc', 'Script-' + BRIDGE_PLUGIN, key, action)
    return reload_bridge()


def reload_bridge():
    """Unload/load the bridge script so readConfig() sees the new corners. Returns True when KWin accepted both calls."""
    path = str(common.SHARE / 'bridge' / 'bridge.js')
    a = sysutil.run(['busctl', '--user', 'call', KWIN, '/Scripting', 'org.kde.kwin.Scripting', 'unloadScript', 's', BRIDGE_PLUGIN])
    b = sysutil.run(['busctl', '--user', 'call', KWIN, '/Scripting', 'org.kde.kwin.Scripting', 'loadScript', 'ss', path, BRIDGE_PLUGIN])
    sysutil.run(['busctl', '--user', 'call', KWIN, '/Scripting', 'org.kde.kwin.Scripting', 'start'])
    return a.code == 0 and b.code == 0
