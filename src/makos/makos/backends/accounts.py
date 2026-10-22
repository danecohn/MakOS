"""Users backend: AccountsService (org.freedesktop.Accounts) over the system D-Bus. Passwords are never handled here:
changing one launches the system `passwd` program in a terminal where the user types it directly."""
import os
import re
import shutil
from pathlib import Path

from . import sysutil
from .bluetooth import _unwrap  # busctl -j value flattening

IFACE = 'org.freedesktop.Accounts.User'
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.svg')
MAX_PICTURE = 4_000_000


def user_path(uid=None):
    uid = os.getuid() if uid is None else int(uid)
    import json
    res = sysutil.run(['busctl', '--system', '-j', 'call', 'org.freedesktop.Accounts', '/org/freedesktop/Accounts', 'org.freedesktop.Accounts',
                       'FindUserById', 'x', str(uid)])
    if res.code != 0:
        return None
    try:
        return json.loads(res.out)['data'][0]
    except (ValueError, KeyError, IndexError):
        return None


def current():
    """Facts about the signed-in user (no secrets)."""
    import json
    uid = os.getuid()
    info = {'uid': uid, 'username': os.environ.get('USER') or '', 'real_name': '', 'icon': '', 'admin': None, 'automatic_login': None,
            'locked': None, 'language': ''}
    path = user_path(uid)
    if path:
        res = sysutil.run(['busctl', '--system', '-j', 'call', 'org.freedesktop.Accounts', path, 'org.freedesktop.DBus.Properties', 'GetAll', 's', IFACE])
        try:
            props = _unwrap(json.loads(res.out)['data'][0])
            info.update({'username': props.get('UserName', info['username']), 'real_name': props.get('RealName', ''),
                         'icon': props.get('IconFile', ''), 'admin': props.get('AccountType') == 1, 'automatic_login': props.get('AutomaticLogin'),
                         'locked': props.get('Locked'), 'language': props.get('Language', '')})
        except (ValueError, KeyError, IndexError):
            pass
    face = Path.home() / '.face'
    if not info['icon'] and face.exists():
        info['icon'] = str(face)
    return info


def check_real_name(name):
    name = (name or '').strip()
    if not 1 <= len(name) <= 64 or re.search(r'[\x00-\x1f:]', name):
        raise ValueError('Enter a name of up to 64 characters (no colons).')
    return name


def set_real_name(name):
    name = check_real_name(name)
    path = user_path()
    if not path:
        return False
    return sysutil.run(['busctl', '--system', 'call', 'org.freedesktop.Accounts', path, IFACE, 'SetRealName', 's', name], timeout=15).code == 0


def check_picture(path):
    p = Path(path)
    if p.suffix.lower() not in IMAGE_EXT or not p.is_file():
        raise ValueError('Choose a PNG, JPEG, WebP or SVG image.')
    if p.stat().st_size > MAX_PICTURE:
        raise ValueError('That picture is larger than 4 MB.')
    return p


def set_picture(path):
    """Copy the picture to ~/.face (readable by the account service and by KDE) and register it with AccountsService."""
    src = check_picture(path)
    face = Path.home() / '.face'
    shutil.copyfile(src, face)
    os.chmod(face, 0o644)
    user = user_path()
    if not user:
        return True
    return sysutil.run(['busctl', '--system', 'call', 'org.freedesktop.Accounts', user, IFACE, 'SetIconFile', 's', str(face)], timeout=15).code == 0


def password_command():
    """argv that opens a terminal running `passwd` for the current user. The password is typed in that terminal, never here."""
    for term, args in (('ptyxis', ['--new-window', '--', 'passwd']), ('konsole', ['-e', 'passwd']), ('x-terminal-emulator', ['-e', 'passwd'])):
        if sysutil.have(term):
            return [term] + args
    return None


def change_password():
    argv = password_command()
    return bool(argv) and sysutil.popen(argv) is not None
