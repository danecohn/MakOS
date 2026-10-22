"""Qt skin plumbing for MakkOS sessions: which platform theme/style to use, and the qt6ct config.

Policy (only ever applied inside a MakkOS session, through ``python3 -m makos.qtskin env``):
  * qt6ct installed        -> QT_QPA_PLATFORMTHEME=qt6ct, Fusion + MakkOS palette + MakkOS QSS (default, verified in the rig)
  * Kvantum installed      -> style kvantum with the MakkOS theme (experimental; MAKOS_QT_STYLE=kvantum opts in)
  * MAKOS_QT_PLATFORMTHEME=kde (needs plasma-integration) is the only way a Qt app exports its menu to the
    shell's global menu on Wayland; the colours then come from the user's KDE scheme unless Kvantum is active.
Nothing here touches the user's config except creating ``qt6ct/qt6ct.conf`` and ``Kvantum/kvantum.kvconfig``
when they do not exist; both are read only when the matching style/platform theme is selected, which only a MakkOS
session does. GPL-3.0-only.
"""
import glob
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1]
SHARE = Path(os.environ.get('MAKOS_SHARE', _SRC if (_SRC / 'theme').exists() else '/usr/share/makos'))
QT_DIR = SHARE / 'theme' / 'qt'

# QPalette role order used by qt6ct colour schemes (Qt 6.x, 21 roles + accent).
ROLES = ['WindowText', 'Button', 'Light', 'Midlight', 'Dark', 'Mid', 'Text', 'BrightText', 'ButtonText', 'Base', 'Window', 'Shadow',
         'Highlight', 'HighlightedText', 'Link', 'LinkVisited', 'AlternateBase', 'NoRole', 'ToolTipBase', 'ToolTipText', 'PlaceholderText', 'Accent']
ACTIVE = ['#242b34', '#ededee', '#ffffff', '#f6f6f7', '#a2a8af', '#c7cbd0', '#242b34', '#ffffff', '#242b34', '#ffffff', '#ececec', '#000000',
          '#2d70c8', '#ffffff', '#1f5fbf', '#6f4aa8', '#f0f4fa', '#000000', '#fffdf0', '#3a3517', '#8a929c', '#418ee6']
DISABLED_FADE = {'WindowText', 'Text', 'ButtonText'}


def _argb(color, alpha=0xff):
    return '#%02x%s' % (alpha, color[1:])


def palette_text():
    active = [_argb(c) for c in ACTIVE]
    inactive = list(active)
    disabled = [_argb(c, 0x73) if r in DISABLED_FADE else _argb(c) for r, c in zip(ROLES, ACTIVE)]
    return '[ColorScheme]\nactive_colors=%s\ninactive_colors=%s\ndisabled_colors=%s\n' % (', '.join(active), ', '.join(inactive), ', '.join(disabled))


def qss_text(directory=QT_DIR):
    return (Path(directory) / 'makos.qss').read_text().replace('@DIR@', str(directory))


def qt6ct_conf(qss_path, palette_path):
    return ('[Appearance]\ncolor_scheme_path=%s\ncustom_palette=true\nicon_theme=MakkOS\nstandard_dialogs=default\nstyle=Fusion\n\n'
            '[Fonts]\nfixed="DejaVu Sans Mono,10,-1,5,50,0,0,0,0,0"\ngeneral="DejaVu Sans,10,-1,5,50,0,0,0,0,0"\n\n'
            '[Interface]\ndouble_click_interval=400\ncursor_flash_time=1000\nbuttonbox_layout=0\nmenus_have_icons=false\n'
            'activate_item_on_single_click=1\ndialog_buttons_have_icons=0\nstylesheets=%s\nunderline_shortcut=1\n'
            'wheel_scroll_lines=3\ntoolbutton_style=4\ngui_effects=@Invalid()\nkeyboard_scheme=2\nshow_shortcuts_in_context_menus=true\n'
            % (palette_path, qss_path))


def kvantum_conf():
    return '[General]\ntheme=MakkOS\n'


def write_config(config_home=None, data_home=None):
    """Create the generated files; returns the list of paths written. Existing user config is never overwritten."""
    config_home = Path(config_home or os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    data_home = Path(data_home or os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    made = []
    target = data_home / 'makos' / 'qt'
    target.mkdir(parents=True, exist_ok=True)
    for name, text in (('makos.qss', qss_text()), ('makos-colors.conf', palette_text())):
        (target / name).write_text(text)  # ours: refreshed on every session start
        made.append(target / name)
    for rel, text in (('qt6ct/qt6ct.conf', qt6ct_conf(target / 'makos.qss', target / 'makos-colors.conf')), ('Kvantum/kvantum.kvconfig', kvantum_conf())):
        path = config_home / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            made.append(path)
    return made


def plugin_exists(kind, name, dirs=None):
    patterns = dirs or ['/usr/lib/*/qt6/plugins/%s/*%s*' % (kind, name), '/usr/lib/qt6/plugins/%s/*%s*' % (kind, name)]
    for extra in os.environ.get('QT_PLUGIN_PATH', '').split(':'):
        if extra:
            patterns.append('%s/%s/*%s*' % (extra, kind, name))
    return any(glob.glob(p) for p in patterns)


def environment(env=None, exists=plugin_exists, cursor_dir='/usr/share/icons/MakkOS-Cursors'):
    """Variables to export for a MakkOS session. Pure given ``exists``; honours explicit MAKOS_QT_* overrides."""
    env = os.environ if env is None else env
    out = {}
    want = env.get('MAKOS_QT_PLATFORMTHEME', '')
    style = env.get('MAKOS_QT_STYLE', '')
    kvantum = exists('styles', 'kvantum')
    if want == 'kde' and exists('platformthemes', 'KDEPlasma'):
        out['QT_QPA_PLATFORMTHEME'] = 'kde'
    elif want != 'none' and exists('platformthemes', 'qt6ct'):
        out['QT_QPA_PLATFORMTHEME'] = 'qt6ct'
    if style == 'kvantum' and kvantum:
        out['QT_STYLE_OVERRIDE'] = 'kvantum'
    else:
        out['QT_STYLE_OVERRIDE'] = 'Fusion'
    share = str(SHARE)
    out['XDG_CONFIG_DIRS'] = ':'.join([share + '/theme/xdg'] + [p for p in env.get('XDG_CONFIG_DIRS', '/etc/xdg').split(':') if p and p != share + '/theme/xdg'])
    if Path(cursor_dir).exists() or Path(share, 'icons', 'MakkOS-Cursors').exists():
        out['XCURSOR_THEME'] = 'MakkOS-Cursors'
        out.setdefault('XCURSOR_SIZE', env.get('XCURSOR_SIZE') or '24')
    out['GTK_USE_PORTAL'] = env.get('GTK_USE_PORTAL', '') or ''
    if not out['GTK_USE_PORTAL']:
        del out['GTK_USE_PORTAL']
    return out


def shell_exports(env=None):
    import shlex
    return '\n'.join('export %s=%s' % (k, shlex.quote(v)) for k, v in sorted(environment(env).items()))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'env':
        print(shell_exports())
    elif cmd == 'setup':
        for path in write_config():
            print(path)
    else:
        print('usage: python3 -m makos.qtskin env|setup', file=sys.stderr)
        sys.exit(2)
