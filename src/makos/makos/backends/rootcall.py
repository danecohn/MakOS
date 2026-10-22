"""The only way Settings asks for administrator rights: `pkexec <fixed helper> <allowlisted action> [validated args]`.

The helper (src/makos/helpers/makos-settings-helper) re-validates every argument as root. Polkit action:
org.makos.settings.manage (src/makos/helpers/org.makos.settings.policy). Authentication is done by the session's polkit
agent; passwords are never seen by Settings. Tests swap the runner via sysutil.set_runner().
"""
import json
import os
import re

from . import sysutil

HELPER = os.environ.get('MAKOS_SETTINGS_HELPER', '/usr/libexec/makos/makos-settings-helper')
LID_ACTIONS = ('ignore', 'suspend', 'hibernate', 'poweroff', 'lock')
# action -> argument validator (None = no arguments allowed). Mirrors the helper's own allowlist.
ACTIONS = {
    'firewall-status': None, 'firewall-enable': None, 'firewall-disable': None,
    'apt-update': None, 'apt-upgrade': None,
    'battery-threshold': lambda a: bool(re.fullmatch(r'[0-9]{2,3}', a)) and 50 <= int(a) <= 100,
    'lid-action': lambda a: a in LID_ACTIONS,
}


def call(action, *args, timeout=60):
    if action not in ACTIONS:
        raise ValueError('That action is not allowed.')
    check = ACTIONS[action]
    if check is None and args:
        raise ValueError(f'{action} takes no arguments.')
    if check is not None and (len(args) != 1 or not check(str(args[0]))):
        raise ValueError(f'Invalid argument for {action}.')
    res = sysutil.run(['pkexec', HELPER, action, *[str(a) for a in args]], timeout=timeout)
    return {'ok': res.code == 0, 'cancelled': res.code in (126, 127) and not res.out,
            'output': (res.out or '')[-2000:], 'error': '' if res.code == 0 else (res.err or res.out)[-300:]}


def firewall_state():
    """Read-only, needs no rights: /etc/ufw/ufw.conf is world-readable. None = ufw not installed."""
    if not os.path.exists('/usr/sbin/ufw'):
        return None
    try:
        for line in open('/etc/ufw/ufw.conf', encoding='utf-8'):
            if line.strip().startswith('ENABLED='):
                return line.split('=', 1)[1].strip().lower() == 'yes'
    except OSError:
        return False
    return False


def parse_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return {}
