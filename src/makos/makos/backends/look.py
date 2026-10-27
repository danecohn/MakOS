"""Appearance backend: MakkOS's own preferences (settings.json; the shell re-reads them live) plus the toolkit keys that make
other applications follow (animation speed, GTK overlay scrolling)."""
from .. import common
from ..settings import model
from . import sysutil

GNOME = 'org.gnome.desktop.interface'


def get(key):
    return common.load_settings()[key]


def put(**values):
    """Merge validated keys into settings.json and return the cleaned settings."""
    data = common.load_settings()
    data.update(values)
    model.clean(data)
    common.save_settings(data)
    return data


def set_accent(name):
    if name not in model.ACCENTS:
        raise ValueError('Unknown accent colour.')
    return put(accent=name, graphite=name == 'graphite')


def set_dark(on):
    return put(dark=bool(on))


def set_font_size(px):
    px = int(px)
    if not 10 <= px <= 18:
        raise ValueError('Font size must be between 10 and 18.')
    return put(font_size=px)


def set_scrollbars(mode):
    if mode not in model.SCROLLBARS:
        raise ValueError('Scroll bars are either automatic or always visible.')
    # other GTK applications follow through the standard overlay-scrolling key
    sysutil.gsettings_set(GNOME, 'overlay-scrolling', 'true' if mode == 'auto' else 'false')
    return put(scrollbars=mode)


def set_reduce_transparency(on):
    return put(reduce_transparency=bool(on))


def set_pinstripes(on):
    return put(pinstripes=bool(on))


def set_reduce_motion(on):
    """MakkOS animations (GTK) and KWin's animation speed (written to the compositor's own config and the user's)."""
    on = bool(on)
    sysutil.kwrite('kdeglobals', 'KDE', 'AnimationDurationFactor', 0 if on else 1)
    sysutil.gsettings_set(GNOME, 'enable-animations', 'false' if on else 'true')
    sysutil.kwin_reconfigure()
    return put(reduce_motion=on)


def css():
    return model.css(common.load_settings())
