# Adapted for MakkOS from Amerika OS (src/os/amerika/privacy.py), GPL-3.0-only, Artemis Softworks LLC; MakkOS adaptations.
"""Security backend: portal permission store, device-in-use indicators, screen lock (kscreenlockerrc in the compositor config),
recent files, ufw firewall (read-only status; enabling goes through pkexec and makos-settings-helper)."""
import json
import os
from pathlib import Path

from .. import common
from . import audio, rootcall, sysutil
from .bluetooth import _unwrap

STORE = ['--user', '-j', 'call', 'org.freedesktop.impl.portal.PermissionStore', '/org/freedesktop/impl/portal/PermissionStore',
         'org.freedesktop.impl.portal.PermissionStore']
RESOURCES = [('devices', 'camera', 'Camera'), ('devices', 'microphone', 'Microphone'), ('location', 'location', 'Location'),
             ('screenshot', 'screenshot', 'Screenshots and screen sharing'), ('background', 'background', 'Run in the background')]
VALUES = ('yes', 'no', 'ask')


def _store(method, *args):
    return sysutil.run(['busctl'] + STORE + [method, *args], timeout=6)


def permissions(table, resource):
    """{app id: 'yes'|'no'|'ask'} for one resource."""
    res = _store('Lookup', 'ss', table, resource)
    if res.code != 0 or not res.out:
        return {}
    try:
        data = _unwrap(json.loads(res.out)['data'][0])
    except (ValueError, KeyError, IndexError):
        return {}
    out = {}
    for app, vals in (data or {}).items():
        v = vals[0] if vals else 'ask'
        out[app] = v if v in VALUES else 'ask'
    return out


def all_permissions():
    out = []
    for table, resource, title in RESOURCES:
        out.append({'table': table, 'resource': resource, 'title': title, 'apps': permissions(table, resource)})
    return out


def set_permission(table, resource, app, value):
    if value not in VALUES:
        raise ValueError('permission must be yes, no or ask')
    if (table, resource) not in {(t, r) for t, r, _n in RESOURCES}:
        raise ValueError('unknown permission')
    if not app or len(app) > 200 or any(c in app for c in '\x00\n'):
        raise ValueError('invalid app id')
    res = _store('SetPermission', 'sbssas', table, 'true', resource, app, '1', value)
    return res.code == 0


def camera_users():
    res = sysutil.run(['pw-dump'], timeout=6)
    if res.code != 0 or not res.out:
        return []
    try:
        nodes = json.loads(res.out)
    except ValueError:
        return []
    names = []
    for n in nodes:
        info = n.get('info', {})
        props = info.get('props', {})
        if n.get('type') == 'PipeWire:Interface:Node' and props.get('media.class') == 'Stream/Input/Video' and info.get('state') == 'running':
            names.append(props.get('application.name') or props.get('node.name') or 'An app')
    return names


def location_in_use():
    res = sysutil.run(['busctl', '--system', 'get-property', 'org.freedesktop.GeoClue2', '/org/freedesktop/GeoClue2/Manager',
                       'org.freedesktop.GeoClue2.Manager', 'InUse'])
    return res.code == 0 and res.out.endswith('true')


def indicators():
    return {'camera': camera_users(), 'microphone': audio.mic_users(), 'location': location_in_use()}


# ---------------------------------------------------------------- screen lock (KWin's screen locker reads kscreenlockerrc)
def lock_settings():
    return {'auto_lock': sysutil.kread('kscreenlockerrc', 'Daemon', 'Autolock', 'true') == 'true',
            'timeout_min': int(sysutil.kread('kscreenlockerrc', 'Daemon', 'Timeout', '5') or 5),
            'lock_on_resume': sysutil.kread('kscreenlockerrc', 'Daemon', 'LockOnResume', 'true') == 'true',
            'grace_seconds': int(sysutil.kread('kscreenlockerrc', 'Daemon', 'LockGrace', '5') or 5)}


def set_lock(auto_lock=None, timeout_min=None, lock_on_resume=None, grace_seconds=None):
    if auto_lock is not None:
        sysutil.kwrite('kscreenlockerrc', 'Daemon', 'Autolock', bool(auto_lock))
    if timeout_min is not None:
        timeout_min = int(timeout_min)
        if not 1 <= timeout_min <= 240:
            raise ValueError('The lock timeout must be between 1 and 240 minutes.')
        sysutil.kwrite('kscreenlockerrc', 'Daemon', 'Timeout', timeout_min)
    if lock_on_resume is not None:
        sysutil.kwrite('kscreenlockerrc', 'Daemon', 'LockOnResume', bool(lock_on_resume))
    if grace_seconds is not None:
        sysutil.kwrite('kscreenlockerrc', 'Daemon', 'LockGrace', max(0, min(300, int(grace_seconds))))
    sysutil.kwin_reconfigure()
    return lock_settings()


def lock_now():
    return sysutil.run(['loginctl', 'lock-session']).code == 0


# ---------------------------------------------------------------- recent files
RECENT = 'recently-used.xbel'
EMPTY_XBEL = ('<?xml version="1.0" encoding="UTF-8"?>\n<xbel version="1.0" xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks" '
              'xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info">\n</xbel>\n')


def recent_enabled():
    return sysutil.gsettings_get('org.gnome.desktop.privacy', 'remember-recent-files', 'true') != 'false'


def set_recent_enabled(on):
    sysutil.gsettings_set('org.gnome.desktop.privacy', 'remember-recent-files', 'true' if on else 'false')
    return bool(on)


def clear_recent():
    """Forget the recent-files list (the files themselves are not touched)."""
    path = sysutil.data_home() / RECENT
    if path.exists():
        path.write_text(EMPTY_XBEL, encoding='utf-8')
    return True


def recent_count():
    try:
        return (sysutil.data_home() / RECENT).read_text(encoding='utf-8').count('<bookmark ')
    except OSError:
        return 0


# ---------------------------------------------------------------- firewall
def firewall_enabled():
    """Read-only (no rights needed). None = ufw not installed."""
    return rootcall.firewall_state()


def set_firewall(on):
    return rootcall.call('firewall-enable' if on else 'firewall-disable')
