# Adapted for MakkOS from Amerika OS (src/os/amerika/updates.py), GPL-3.0-only, Artemis Softworks LLC; MakkOS adaptations.
"""Updates backend: read-only apt state plus privileged actions that always go through pkexec and the fixed MakkOS helper
(`makos-settings-helper apt-update | apt-upgrade`: no arguments, never dist-upgrade, login manager preserved).
Nothing here ever runs apt directly with elevated rights.
"""
import os
import re
import time
from pathlib import Path

from . import sysutil

from . import rootcall

SETTINGS_HELPER = rootcall.HELPER
STAMPS = ('/var/lib/apt/periodic/update-success-stamp', '/var/lib/apt/lists')
REBOOT_FLAG = Path('/var/run/reboot-required')
_LINE = re.compile(r'^(?P<name>[^/\s]+)/(?P<suite>\S+)\s+(?P<new>\S+)\s+(?P<arch>\S+)(?:\s+\[upgradable from: (?P<old>[^\]]+)\])?')


def upgradable():
    res = sysutil.run(['apt', 'list', '--upgradable'], timeout=20, env={'LANG': 'C', 'LC_ALL': 'C'})
    out = []
    for line in res.out.splitlines():
        m = _LINE.match(line)
        if m:
            suite = m.group('suite')
            out.append({'name': m.group('name'), 'new': m.group('new'), 'old': m.group('old') or '', 'suite': suite,
                        'security': 'security' in suite})
    return out


def last_refresh():
    for p in STAMPS:
        try:
            return int(os.stat(p).st_mtime)
        except OSError:
            continue
    return None


def ago(ts, now=None):
    if not ts:
        return 'never'
    delta = int((now or time.time()) - ts)
    if delta < 90:
        return 'just now'
    if delta < 5400:
        return f'{delta // 60} minutes ago'
    if delta < 172800:
        return f'{delta // 3600} hours ago'
    return f'{delta // 86400} days ago'


def status():
    ups = upgradable()
    return {'upgradable': ups, 'count': len(ups), 'security': sum(1 for u in ups if u['security']),
            'last_refresh': last_refresh(), 'reboot_required': REBOOT_FLAG.exists()}


def refresh():
    return rootcall.call('apt-update', timeout=1800)


def upgrade():
    return rootcall.call('apt-upgrade', timeout=3600)
