# Adapted for MakkOS from Amerika OS (src/os/amerika/sharing.py), GPL-3.0-only, VigilTech; MakkOS adaptations.
"""Sharing & remote desktop backend: read-only status of the services that expose this computer, plus user-level toggles
for the remote-desktop service where one exists. System services (SSH, Samba) are shown with the exact command to
enable them; nothing here changes them."""
from . import sysutil

SERVICES = [
    # id, label, scope, candidate unit names, how to turn it on (shown, not run)
    ('rdp', 'Remote desktop (RDP)', 'user', ['plasma-krdp_server.service', 'gnome-remote-desktop.service'], None),
    ('ssh', 'Remote login (SSH)', 'system', ['ssh.service', 'sshd.service'], 'sudo apt install openssh-server  then  sudo systemctl enable --now ssh'),
    ('samba', 'File sharing (Windows / SMB)', 'system', ['smbd.service'], 'sudo apt install samba  then  sudo systemctl enable --now smbd'),
    ('mdns', 'Local network discovery (Avahi)', 'system', ['avahi-daemon.service'], 'sudo systemctl enable --now avahi-daemon'),
]


def _unit_exists(unit, scope):
    argv = ['systemctl'] + (['--user'] if scope == 'user' else []) + ['show', '-p', 'LoadState', '--value', unit]
    return sysutil.run(argv).out == 'loaded'


def _active(unit, scope):
    argv = ['systemctl'] + (['--user'] if scope == 'user' else []) + ['is-active', unit]
    return sysutil.run(argv).out == 'active'


def _enabled(unit, scope):
    argv = ['systemctl'] + (['--user'] if scope == 'user' else []) + ['is-enabled', unit]
    return sysutil.run(argv).out in ('enabled', 'enabled-runtime', 'static')


def status():
    out = []
    for sid, name, scope, units, how in SERVICES:
        unit = next((u for u in units if _unit_exists(u, scope)), None)
        out.append({'id': sid, 'name': name, 'scope': scope, 'unit': unit, 'installed': bool(unit),
                    'active': bool(unit) and _active(unit, scope), 'enabled': bool(unit) and _enabled(unit, scope), 'how': how,
                    'toggle': scope == 'user' and bool(unit)})
    return out


def hostname():
    res = sysutil.run(['hostname'])
    return res.out or ''


def set_user_service(unit, on):
    allowed = {u for _i, _n, scope, units, _h in SERVICES if scope == 'user' for u in units}
    if unit not in allowed:
        raise ValueError('That service cannot be changed from here.')
    res = sysutil.run(['systemctl', '--user', 'start' if on else 'stop', unit], timeout=15)
    return res.code == 0
