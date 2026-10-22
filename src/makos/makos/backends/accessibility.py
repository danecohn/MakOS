"""Accessibility backend: text size, contrast and motion (MakOS + toolkit keys), keyboard aids (kaccessrc), Orca, KWin zoom."""
from .. import common
from . import look, sysutil

GNOME_IFACE = 'org.gnome.desktop.interface'
TEXT_SCALES = [(1.0, 'Normal'), (1.15, 'Large'), (1.3, 'Larger'), (1.5, 'Largest')]


def state():
    s = common.load_settings()
    return {'text_scale': s['text_scale'], 'high_contrast': s['high_contrast'], 'reduce_motion': s['reduce_motion'],
            'reduce_transparency': s['reduce_transparency'],
            'sticky_keys': sysutil.kread('kaccessrc', 'Keyboard', 'StickyKeys', 'false') == 'true',
            'slow_keys': sysutil.kread('kaccessrc', 'Keyboard', 'SlowKeys', 'false') == 'true',
            'slow_keys_delay': int(sysutil.kread('kaccessrc', 'Keyboard', 'SlowKeysDelay', '300') or 300),
            'bounce_keys': sysutil.kread('kaccessrc', 'Keyboard', 'BounceKeys', 'false') == 'true',
            'bounce_keys_delay': int(sysutil.kread('kaccessrc', 'Keyboard', 'BounceKeysDelay', '300') or 300),
            'screen_reader': sysutil.gsettings_get('org.gnome.desktop.a11y.applications', 'screen-reader-enabled', 'false') == 'true',
            'orca_installed': sysutil.have('orca'), 'zoom': zoom_enabled(),
            'zoom_level': float(sysutil.kread('kwinrc', 'Effect-zoom', 'InitialZoom', '1.5') or 1.5)}


def set_text_scale(scale):
    scale = float(scale)
    if not 1.0 <= scale <= 2.0:
        raise ValueError('Text scale must be between 1.0 and 2.0.')
    sysutil.gsettings_set(GNOME_IFACE, 'text-scaling-factor', scale)  # other GTK applications
    look.put(text_scale=scale)  # MakOS applications (CSS)
    return scale


def set_high_contrast(on):
    look.put(high_contrast=bool(on))
    sysutil.gsettings_set('org.gnome.desktop.a11y.interface', 'high-contrast', 'true' if on else 'false')
    return bool(on)


def set_reduce_motion(on):
    return look.set_reduce_motion(on)["reduce_motion"]


def set_reduce_transparency(on):
    return look.set_reduce_transparency(on)['reduce_transparency']


def set_keys(sticky=None, slow=None, slow_delay=None, bounce=None, bounce_delay=None):
    if sticky is not None:
        sysutil.kwrite('kaccessrc', 'Keyboard', 'StickyKeys', bool(sticky))
    if slow is not None:
        sysutil.kwrite('kaccessrc', 'Keyboard', 'SlowKeys', bool(slow))
    if slow_delay is not None:
        sysutil.kwrite('kaccessrc', 'Keyboard', 'SlowKeysDelay', max(50, min(2000, int(slow_delay))))
    if bounce is not None:
        sysutil.kwrite('kaccessrc', 'Keyboard', 'BounceKeys', bool(bounce))
    if bounce_delay is not None:
        sysutil.kwrite('kaccessrc', 'Keyboard', 'BounceKeysDelay', max(50, min(2000, int(bounce_delay))))
    sysutil.kwin_reconfigure()
    sysutil.run(['busctl', '--user', 'call', 'org.kde.kaccess', '/kaccess', 'org.kde.kaccess', 'reconfigure'])
    return state()


def set_screen_reader(on):
    on = bool(on)
    if not sysutil.have('orca'):
        return False
    sysutil.gsettings_set('org.gnome.desktop.a11y.applications', 'screen-reader-enabled', 'true' if on else 'false')
    if on:
        sysutil.popen(['orca'])
    else:
        sysutil.run(['orca', '--quit'], timeout=5)
    return True


def zoom_enabled():
    res = sysutil.run(['busctl', '--user', 'call', 'org.kde.KWin', '/Effects', 'org.kde.kwin.Effects', 'isEffectLoaded', 's', 'zoom'])
    return res.code == 0 and res.out.endswith('true')


def set_zoom(on, level=None):
    if level is not None:
        if not 1.0 <= float(level) <= 8.0:
            raise ValueError('Zoom must be between 1x and 8x.')
        sysutil.kwrite('kwinrc', 'Effect-zoom', 'InitialZoom', float(level))
    sysutil.kwrite('kwinrc', 'Plugins', 'zoomEnabled', bool(on))
    sysutil.run(['busctl', '--user', 'call', 'org.kde.KWin', '/Effects', 'org.kde.kwin.Effects', 'loadEffect' if on else 'unloadEffect', 's', 'zoom'])
    sysutil.kwin_reconfigure()
    return bool(on)
