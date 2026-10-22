"""Startup: login items (XDG autostart, user level) and an honest status of the login/boot theme switches.

Login and boot theme switching is NOT offered here: it needs a tested snapshot, revert and recovery implementation owned by
the theme engineer. `theme_switch_status()` reports that truthfully; this module never writes SDDM, Plymouth or PAM files.
"""
import os
import re
from pathlib import Path

from . import sysutil

NAME_OK = re.compile(r'^[A-Za-z0-9_.\-]{1,100}\.desktop$')


def autostart_dir():
    return sysutil.config_home() / 'autostart'


def _entries(directory):
    out = {}
    try:
        files = sorted(directory.glob('*.desktop'))
    except OSError:
        return out
    for f in files:
        try:
            kv = {}
            in_entry = False
            for line in f.read_text(encoding='utf-8', errors='replace').splitlines():
                if line.startswith('['):
                    in_entry = line.strip() == '[Desktop Entry]'
                elif in_entry and '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    kv.setdefault(k.strip(), v.strip())
            out[f.name] = kv
        except OSError:
            continue
    return out


def applies(kv, desktop=None):
    """Whether an autostart entry runs in this desktop (OnlyShowIn / NotShowIn, as the XDG autostart spec defines)."""
    current = {d for d in (desktop or os.environ.get('XDG_CURRENT_DESKTOP') or 'MakOS').split(':') if d}
    only = {d for d in kv.get('OnlyShowIn', '').split(';') if d}
    nots = {d for d in kv.get('NotShowIn', '').split(';') if d}
    return (not only or bool(only & current)) and not (nots & current)


def login_items():
    """[{'id', 'name', 'exec', 'enabled', 'system'}]: system entries (/etc/xdg/autostart) can only be switched off for this user."""
    user = _entries(autostart_dir())
    system = _entries(Path('/etc/xdg/autostart'))
    items = []
    for ident in sorted(set(user) | set(system)):
        kv = {**system.get(ident, {}), **user.get(ident, {})}
        if not applies(kv):
            continue
        items.append({'id': ident, 'name': kv.get('Name', ident.removesuffix('.desktop')), 'exec': kv.get('Exec', ''),
                      'enabled': kv.get('Hidden', 'false').lower() != 'true' and kv.get('X-GNOME-Autostart-enabled', 'true').lower() != 'false',
                      'system': ident in system and ident not in user})
    return items


def set_item_enabled(ident, on):
    """Per-user override: a copy with Hidden=true disables a system entry; removing that override enables it again."""
    if not NAME_OK.match(ident or ''):
        raise ValueError('Invalid login item.')
    user_file = autostart_dir() / ident
    system_file = Path('/etc/xdg/autostart') / ident
    if system_file.exists():
        if on:
            user_file.unlink(missing_ok=True)
        else:
            autostart_dir().mkdir(parents=True, exist_ok=True)
            user_file.write_text('[Desktop Entry]\nType=Application\nHidden=true\n', encoding='utf-8')
        return True
    if user_file.exists():
        text = user_file.read_text(encoding='utf-8', errors='replace')
        text = re.sub(r'(?m)^Hidden=.*\n', '', text)
        if not on:
            text = text.replace('[Desktop Entry]\n', '[Desktop Entry]\nHidden=true\n', 1)
        user_file.write_text(text, encoding='utf-8')
        return True
    raise ValueError('That login item does not exist.')


def theme_switch_status():
    return {'available': False,
            'reason': 'Login and boot theme switches are not available yet. They will only appear once a tested snapshot, '
                      'revert and recovery path exists. Your login manager, boot splash and PAM configuration are untouched.'}
