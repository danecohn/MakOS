"""MakkOS appearance: Glass & Metal tokens, accent colours and the Graphite variant.

The widget themes in ``theme/gtk-{3,4}.0/gtk.css`` are written against ``@define-color mk_*``
tokens and are a complete default (blue) theme on their own. A variant is the same file with
``@define-color`` overrides appended (the later definition wins), so switching appearance at
runtime is one CssProvider reload and the installed static themes (``MakkOS``,
``MakkOS-Graphite``, ``MakkOS-<Accent>``) for third-party GTK apps are generated from the same
text. Pure logic: importing this module does not need GTK or a display. GPL-3.0-only.
"""
import os
import re
import shutil
import sys
from pathlib import Path

ACCENTS = ('blossom', 'blue', 'graphite', 'teal', 'green', 'orange', 'red', 'purple')
# name -> (light, mid, dark, border): original gel colour stops. Kept in step with
# settings.model.ACCENT_COLORS (the settings pane validates names; both use the same set).
_LOCAL = {
    'blossom': ('#ffe0eb', '#ff8cb4', '#ff0058', '#bd0041'),
    'blue': ('#d7efff', '#8cc7ff', '#418ee6', '#3873b1'),
    'graphite': ('#e7e9ec', '#bfc4ca', '#7b838d', '#5d646d'),
    'teal': ('#d4f6f1', '#86ddd0', '#2fa597', '#2a8379'),
    'green': ('#dff5d4', '#9be07f', '#4fae33', '#3f8a2a'),
    'orange': ('#ffe9d0', '#ffbf7a', '#ee8a1c', '#b86a12'),
    'red': ('#ffdcd6', '#ff9d90', '#e0483a', '#a8382d'),
    'purple': ('#eadcff', '#c3a2f5', '#8a55d6', '#6c42a8'),
}
_HEX = re.compile(r'^#[0-9a-f]{6}$')
_SRC = Path(__file__).resolve().parents[1]
THEME_DIR = Path(os.environ.get('MAKOS_SHARE', _SRC if (_SRC / 'theme').exists() else '/usr/share/makos')) / 'theme'


def _colors():
    try:  # single source of truth when the settings pane module is present
        from .settings import model
        table = dict(model.ACCENT_COLORS)
        if set(table) >= set(ACCENTS):
            return table
    except Exception:
        pass
    return _LOCAL


def clean_accent(name):
    return name if name in ACCENTS else 'blue'


def tokens(accent='blue', graphite=False):
    """Return the ``mk_*`` colour overrides for an accent. Graphite forces the neutral accent
    and also greys the window/metal tint slightly (the controls become monochrome)."""
    accent = 'graphite' if graphite else clean_accent(accent)
    light, mid, dark, border = _colors()[accent]
    out = {'mk_acc_light': light, 'mk_acc_mid': mid, 'mk_acc_dark': dark, 'mk_acc_border': border,
           'mk_acc_text': '#2a2200' if accent == 'orange' and False else '#ffffff'}
    if graphite:
        out.update({'mk_sidebar_a': '#e1e3e6', 'mk_sidebar_b': '#d4d7db', 'mk_alt_row': '#f3f4f5', 'mk_window': '#eeeeee'})
    for value in out.values():
        assert _HEX.match(value), value
    return out


def override_css(accent='blue', graphite=False):
    base = tokens('blue', False)
    wanted = tokens(accent, graphite)
    lines = ['/* variant: %s%s */' % ('graphite' if graphite else clean_accent(accent), '')]
    lines += ['@define-color %s %s;' % (k, v) for k, v in wanted.items() if base.get(k) != v or graphite or accent != 'blue']
    css = '\n'.join(lines) + '\n'
    if graphite or clean_accent(accent) == 'graphite':
        # Graphite also quietens the gel: default buttons/progress are grey, not blue.
        css += ('button.suggested-action, button.default { color: #1d242c; }\n'
                'selection, *:selected { background-color: #6f7a87; }\n')
    return css


def theme_css(gtk=4, accent='blue', graphite=False):
    """Full stylesheet text for GTK 3 or 4 including the variant overrides."""
    if gtk not in (3, 4):
        raise ValueError('gtk must be 3 or 4')
    base = (THEME_DIR / ('gtk-%d.0' % gtk) / 'gtk.css').read_text()
    if clean_accent(accent) == 'blue' and not graphite:
        return base
    return base + '\n' + override_css(accent, graphite)


def theme_name(accent='blue', graphite=False):
    if graphite:
        return 'MakkOS-Graphite'
    accent = clean_accent(accent)
    return 'MakkOS' if accent == 'blue' else 'MakkOS-' + accent.title()


def theme_variants():
    """(name, accent, graphite) for every installed static theme."""
    out = [('MakkOS', 'blue', False), ('MakkOS-Graphite', 'graphite', True)]
    out += [(theme_name(a), a, False) for a in ACCENTS if a not in ('blue', 'graphite')]
    return out


def write_themes(dest):
    """Write /usr/share/themes style directories (gtk-3.0/gtk-4.0 each + index.theme) under dest."""
    dest = Path(dest)
    written = []
    for name, accent, graphite in theme_variants():
        root = dest / name
        for gtk in (3, 4):
            target = root / ('gtk-%d.0' % gtk)
            target.mkdir(parents=True, exist_ok=True)
            (target / 'gtk.css').write_text(theme_css(gtk, accent, graphite))
            assets = THEME_DIR / ('gtk-%d.0' % gtk) / 'assets'
            if assets.is_dir():  # GTK 3 cannot read data: URIs in CSS, so its marks are real files
                shutil.copytree(assets, target / 'assets', dirs_exist_ok=True)
        (root / 'index.theme').write_text(
            '[Desktop Entry]\nType=X-GNOME-Metatheme\nName=%s\nComment=MakkOS Glass & Metal%s\n'
            'Encoding=UTF-8\n\n[X-GNOME-Metatheme]\nGtkTheme=%s\nMetacityTheme=%s\nIconTheme=MakkOS\nCursorTheme=MakkOS-Cursors\n'
            % (name, ' (Graphite)' if graphite else '', name, name))
        written.append(root)
    return written


# ------------------------------------------------------------------ runtime (GTK4 shell)
_PROVIDER = {}


def install(display, accent='blue', graphite=False):
    """Load the widget theme for the shell's own GTK4 windows below glass.css (THEME priority)."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk
    provider = _PROVIDER.get('p')
    if provider is None:
        provider = _PROVIDER['p'] = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_THEME)
    provider.load_from_string(theme_css(4, accent, graphite))
    return provider


def set_variant(display, accent='blue', graphite=False):
    """Switch accent/Graphite at runtime."""
    return install(display, accent, graphite)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'install-themes':
        for path in write_themes(sys.argv[2]):
            print(path)
    else:
        print('usage: python3 -m makos.appearance install-themes DIR', file=sys.stderr)
        sys.exit(2)
