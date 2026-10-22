"""GTK helpers shared by the Studio windows: theme + icon setup, small widget builders, async helper."""
import os
import threading
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

STUDIO_CSS = '''
.st-tile { background-image: linear-gradient(to bottom, alpha(white, .09), alpha(white, .02)); border: 1px solid alpha(white, .16);
  border-radius: 22px; padding: 18px; }
.st-tile:hover { border-color: alpha(@am_second, .7); box-shadow: 0 0 22px alpha(@am_second, .28); }
.st-tile.missing { opacity: .72; }
.st-tile-name { font-size: 16px; font-weight: 800; letter-spacing: 1px; color: @am_text; }
.st-tile-sub { font-size: 12px; color: @am_dim; }
.st-brand { font-size: 28px; font-weight: 800; letter-spacing: 7px; color: @am_text; text-shadow: 0 0 22px alpha(@am_accent, .75); }
.st-tag { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: 11px; letter-spacing: 3px; color: @am_second; }
.st-hero { background-image: radial-gradient(circle at 15%% 0%%, alpha(@am_accent, .20), transparent 55%%), linear-gradient(to bottom, #1a1930, #0d0c16);
  border-bottom: 1px solid alpha(@am_accent, .5); box-shadow: 0 1px 16px alpha(@am_accent, .25); padding: 20px 26px; }
.st-ok { color: #39ff88; font-weight: 700; }
.st-warn { color: #ffb02e; font-weight: 700; }
.st-link { background: transparent; border: none; color: @am_second; font-weight: 700; padding: 2px 6px; min-height: 0; }
.st-link:hover { text-decoration: underline; }
.st-row { padding: 6px 8px; border-radius: 10px; }
.st-row:hover { background: alpha(white, .06); }
levelbar trough { background: alpha(white, .12); border-radius: 999px; min-height: 8px; }
levelbar block.filled { background-image: linear-gradient(to right, @am_second, @am_accent); border-radius: 999px; }
dropdown > button { background: alpha(black, .4); border: 1px solid alpha(white, .16); border-radius: 10px; color: @am_text; }
window.st-window { background: @am_bg; color: @am_text; }
'''


def setup(extra_icon_dirs=()):
    """Apply the Amerika theme (when the shell package is installed), the Studio CSS and the icon theme."""
    if os.environ.get('MAKOS_SESSION') == '1':
        from makos.ui import install_theme
        install_theme()
        return
    display = Gdk.Display.get_default()
    icons = Gtk.IconTheme.get_for_display(display)
    dirs = [d for d in os.environ.get('AMERIKA_STUDIO_ICONS', '').split(':') if d] + list(extra_icon_dirs) + [d for d in [icon_dir_dev()] if d]
    if dirs:
        icons.set_search_path(dirs + list(icons.get_search_path() or []))
    dev_icons = os.environ.get('AMERIKA_ICONS')
    if dev_icons:
        icons.set_search_path([dev_icons] + list(icons.get_search_path() or []))
    Gtk.Settings.get_default().set_property('gtk-icon-theme-name', 'AmerikaOS')
    accent, second = '#ff2e63', '#19e3ff'
    try:
        from amerika import common as acommon, theme
        s = acommon.load_settings()
        accent, second = s.get('accent', accent), s.get('secondary', second)
        theme.apply(accent, second)
    except Exception:  # noqa: BLE001 - without the shell package we still draw with the Studio CSS alone
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', True)
        fallback = Gtk.CssProvider()
        fallback.load_from_string(FALLBACK_CSS.replace('%(accent)s', accent).replace('%(second)s', second))
        Gtk.StyleContext.add_provider_for_display(display, fallback, Gtk.STYLE_PROVIDER_PRIORITY_USER - 1)
    css = Gtk.CssProvider()
    css.load_from_string(STUDIO_CSS % {})
    Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_USER)


FALLBACK_CSS = '''
@define-color am_bg #0b0a14; @define-color am_text #ecebf5; @define-color am_dim #9a98b0;
@define-color am_accent %(accent)s; @define-color am_second %(second)s;
.am-card { background: alpha(white, .05); border: 1px solid alpha(white, .14); border-radius: 18px; padding: 16px; }
.am-heading { font-size: 22px; font-weight: 800; } .am-sub { color: @am_dim; font-size: 12px; }
.am-label { font-size: 10px; font-weight: 700; letter-spacing: 2px; color: @am_dim; }
.am-primary { background: @am_accent; color: white; border-radius: 12px; padding: 8px 18px; font-weight: 800; }
.am-secondary { background: alpha(white, .1); color: @am_text; border-radius: 12px; padding: 8px 18px; }
.am-pill { border-radius: 999px; padding: 1px 10px; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; }
.am-pill.on { color: #0b0a14; background: #39ff88; } .am-pill.off { color: @am_dim; background: alpha(white, .08); }
.am-keystate { font-size: 11px; font-weight: 700; letter-spacing: 1px; color: @am_dim; } .am-keystate.saved { color: #39ff88; }
'''


def label(text, css=None, xalign=0.0, wrap=False):
    lab = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    for c in (css or '').split():
        lab.add_css_class(c)
    return lab


def card(*children, spacing=10, css=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.add_css_class('am-card')
    for c in (css or '').split():
        box.add_css_class(c)
    for c in children:
        box.append(c)
    return box


def clear(box):
    child = box.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def button(text, css='am-secondary', on_click=None, **kw):
    b = Gtk.Button(label=text, **kw)
    b.add_css_class(css)
    if on_click:
        b.connect('clicked', lambda *_: on_click())
    return b


def in_thread(work, done=None):
    """Run work() in a thread; call done(result, error) on the GTK main loop."""
    def runner():
        try:
            res, err = work(), None
        except Exception as e:  # noqa: BLE001 - relayed to done()
            res, err = None, e
        if done:
            GLib.idle_add(lambda: (done(res, err), False)[1])
    threading.Thread(target=runner, daemon=True).start()


def set_pill(widget, text, on):
    widget.set_label(text)
    widget.remove_css_class('on')
    widget.remove_css_class('off')
    widget.add_css_class('on' if on else 'off')


def icon_dir_dev():
    here = Path(__file__).resolve().parent.parent / 'icons'
    return str(here) if here.is_dir() else None
