"""VigilOS appearance: VigilTech tokens, accent colours, Graphite and the Night (dark) variant.

The widget themes in ``theme/gtk-{3,4}.0/gtk.css`` are written against ``@define-color mk_*``
tokens and are a complete default (light, rose) theme on their own. A variant is the same file with
``@define-color`` overrides appended (the later definition wins), so switching appearance at
runtime is one CssProvider reload and the installed static themes (``MakkOS``,
``MakkOS-Graphite``, ``MakkOS-Night``, ``MakkOS-<Accent>``) for third-party GTK apps are generated from the same
text. The theme directory names keep the ``MakkOS`` prefix so saved selections keep working.
Pure logic: importing this module does not need GTK or a display. GPL-3.0-only.
"""
import os
import re
import shutil
import sys
from pathlib import Path

ACCENTS = ('blossom', 'blue', 'graphite', 'teal', 'green', 'orange', 'red', 'purple')
# name -> (light, mid, dark, border): light = soft tint, mid = highlight, dark = control fill (white text on it is
# at least 4.5:1), border = fill edge. Kept in step with settings.model.ACCENT_COLORS (the settings pane validates
# names; both use the same set).
_LOCAL = {
    'blossom': ('#ffd6e4', '#ff4d86', '#d6004a', '#a8003a'),
    'blue': ('#dbe9ff', '#7aa7f5', '#1f5fbf', '#174a96'),
    'graphite': ('#e7e3e6', '#a9a0a6', '#5d4e5a', '#453842'),
    'teal': ('#d4f6f1', '#59b9ad', '#0f7a6e', '#0b5d54'),
    'green': ('#dff5d4', '#7bc063', '#2e7d20', '#245f19'),
    'orange': ('#ffe9d0', '#e59a3f', '#a8530a', '#823f07'),
    'red': ('#ffdcd6', '#f07a6c', '#b3261a', '#8a1d14'),
    'purple': ('#eadcff', '#a98be0', '#6d3bc0', '#552e97'),
}
# Night (dark) appearance: plum-black surfaces, bone text.
_NIGHT = {
    'mk_text': '#f7eef2', 'mk_text_dim': '#bfaebb', 'mk_window': '#120a14', 'mk_base': '#1e1422', 'mk_bar': '#1a1020',
    'mk_border': '#8f7b8b', 'mk_border_soft': '#3a2a3d', 'mk_sidebar_a': '#181019', 'mk_sidebar_b': '#150d17',
    'mk_alt_row': '#231727', 'mk_hover': '#2d1f31', 'mk_pressed': '#3b2a3f', 'mk_focus': '#ff7aa6', 'mk_link': '#ff7aa6',
    'mk_warning': '#ffb066', 'mk_error': '#ff7a8e', 'mk_success': '#7fd18b', 'mk_menu': '#241829',
}
_HEX = re.compile(r'^#[0-9a-f]{6}$')
_SRC = Path(__file__).resolve().parents[1]
THEME_DIR = Path(os.environ.get('MAKOS_SHARE', _SRC if (_SRC / 'theme').exists() else '/usr/share/makos')) / 'theme'
DEFAULT_ACCENT = 'blossom'


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
    return name if name in ACCENTS else DEFAULT_ACCENT


def tokens(accent=DEFAULT_ACCENT, graphite=False, dark=False):
    """Return the ``mk_*`` colour overrides for an accent. Graphite forces the neutral accent
    (controls become monochrome). Night adds the dark surface and text tokens."""
    accent = 'graphite' if graphite else clean_accent(accent)
    light, mid, dark_, border = _colors()[accent]
    out = {'mk_acc_light': light, 'mk_acc_mid': mid, 'mk_acc_dark': dark_, 'mk_acc_border': border, 'mk_acc_text': '#ffffff'}
    if dark:
        out.update(_NIGHT)
        if accent == 'graphite':
            out.update({'mk_acc_dark': '#7a6877', 'mk_acc_border': '#9a8798'})
            out['mk_acc_text'] = '#ffffff'
    for value in out.values():
        assert _HEX.match(value), value
    return out


def _night_marks(gtk):
    fill = '%23bfaebb'
    if gtk == 4:
        def uri(path):
            return 'url("data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' width=\'16\' height=\'16\'>%s</svg>")' % path
        down = uri("<path d='M4 6.2 8 10 12 6.2' fill='none' stroke='%s' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/>" % fill)
        right = uri("<path d='M6 3.5 11 8 6 12.5Z' fill='%s'/>" % fill)
        solid = uri("<path d='M3.5 6 8 11 12.5 6Z' fill='%s'/>" % fill)
    else:
        down, right, solid = ('url("assets/arrow-down-light.svg")', 'url("assets/arrow-right-light.svg")', 'url("assets/arrow-down-solid-light.svg")')
    return ('combobox arrow, dropdown arrow, menubutton arrow { -gtk-icon-source: %s; }\n'
            'treeview.view.expander, expander arrow, expander title arrow, expander title > expander { -gtk-icon-source: %s; }\n'
            'treeview.view.expander:checked, expander arrow:checked, expander title arrow:checked, expander title > expander:checked { -gtk-icon-source: %s; }\n'
            'switch slider, scale slider { background: #f7eef2; }\n'
            'infobar { background: #3b2a00; color: #ffe9b0; } infobar label { color: #ffe9b0; }\n'
            'infobar.error { background: #4a0f1a; color: #ffd3da; } infobar.error label { color: #ffd3da; }\n'
            'infobar.info, infobar.question { background: #12264d; color: #d6e4ff; } infobar.info label, infobar.question label { color: #d6e4ff; }\n'
            'tooltip, tooltip.background { background: #f7eef2; } tooltip label { color: #17101a; }\n'
            '@define-color mk_tooltip #f7eef2;\n@define-color mk_tooltip_text #17101a;\n') % (down, right, solid)


def override_css(accent=DEFAULT_ACCENT, graphite=False, dark=False, gtk=4):
    base = tokens(DEFAULT_ACCENT, False, False)
    wanted = tokens(accent, graphite, dark)
    lines = ['/* variant: %s%s */' % ('graphite' if graphite else clean_accent(accent), ' night' if dark else '')]
    lines += ['@define-color %s %s;' % (k, v) for k, v in wanted.items() if base.get(k) != v or graphite or dark or clean_accent(accent) != DEFAULT_ACCENT]
    css = '\n'.join(lines) + '\n'
    if dark:
        css += _night_marks(gtk)
    return css


def theme_css(gtk=4, accent=DEFAULT_ACCENT, graphite=False, dark=False):
    """Full stylesheet text for GTK 3 or 4 including the variant overrides."""
    if gtk not in (3, 4):
        raise ValueError('gtk must be 3 or 4')
    base = (THEME_DIR / ('gtk-%d.0' % gtk) / 'gtk.css').read_text()
    if clean_accent(accent) == DEFAULT_ACCENT and not graphite and not dark:
        return base
    return base + '\n' + override_css(accent, graphite, dark, gtk)


def theme_name(accent=DEFAULT_ACCENT, graphite=False, dark=False):
    if dark:
        return 'MakkOS-Night'
    if graphite:
        return 'MakkOS-Graphite'
    accent = clean_accent(accent)
    return 'MakkOS' if accent == DEFAULT_ACCENT else 'MakkOS-' + accent.title()


def theme_variants():
    """(name, accent, graphite, dark) for every installed static theme."""
    out = [('MakkOS', DEFAULT_ACCENT, False, False), ('MakkOS-Graphite', 'graphite', True, False), ('MakkOS-Night', DEFAULT_ACCENT, False, True)]
    out += [(theme_name(a), a, False, False) for a in ACCENTS if a not in (DEFAULT_ACCENT, 'graphite')]
    return out


def write_themes(dest):
    """Write /usr/share/themes style directories (gtk-3.0/gtk-4.0 each + index.theme) under dest."""
    dest = Path(dest)
    written = []
    for name, accent, graphite, dark in theme_variants():
        root = dest / name
        for gtk in (3, 4):
            target = root / ('gtk-%d.0' % gtk)
            target.mkdir(parents=True, exist_ok=True)
            (target / 'gtk.css').write_text(theme_css(gtk, accent, graphite, dark))
            assets = THEME_DIR / ('gtk-%d.0' % gtk) / 'assets'
            if assets.is_dir():  # GTK 3 cannot read data: URIs in CSS, so its marks are real files
                shutil.copytree(assets, target / 'assets', dirs_exist_ok=True)
        (root / 'index.theme').write_text(
            '[Desktop Entry]\nType=X-GNOME-Metatheme\nName=%s\nComment=VigilOS%s\n'
            'Encoding=UTF-8\n\n[X-GNOME-Metatheme]\nGtkTheme=%s\nMetacityTheme=%s\nIconTheme=MakkOS\nCursorTheme=MakkOS-Cursors\n'
            % (name, ' (Graphite)' if graphite else ' (Night)' if dark else '', name, name))
        written.append(root)
    return written


# ------------------------------------------------------------------ runtime (GTK4 shell)
_PROVIDER = {}


def install(display, accent=DEFAULT_ACCENT, graphite=False, dark=False):
    """Load the widget theme for the shell's own GTK4 windows below glass.css (THEME priority)."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk
    provider = _PROVIDER.get('p')
    if provider is None:
        provider = _PROVIDER['p'] = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_THEME)
    provider.load_from_string(theme_css(4, accent, graphite, dark))
    return provider


def set_variant(display, accent=DEFAULT_ACCENT, graphite=False, dark=False):
    """Switch accent/Graphite at runtime."""
    return install(display, accent, graphite, dark)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'install-themes':
        for path in write_themes(sys.argv[2]):
            print(path)
    else:
        print('usage: python3 -m makos.appearance install-themes DIR', file=sys.stderr)
        sys.exit(2)
