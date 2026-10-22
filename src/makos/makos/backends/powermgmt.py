"""Energy backend: power profiles (power-profiles-daemon), battery facts (UPower), lid action and charge limit (through the
root helper), idle/screen-off actions (powerdevil, only when that service is running in the session)."""
import json
from pathlib import Path

from . import rootcall, sysutil
from .bluetooth import _unwrap

PROFILES = [('power-saver', 'Power saver'), ('balanced', 'Balanced'), ('performance', 'Performance')]
LID_CHOICES = [('suspend', 'Sleep'), ('hibernate', 'Hibernate'), ('lock', 'Lock the screen'), ('poweroff', 'Shut down'), ('ignore', 'Do nothing')]
ACTIONS = [(0, 'Do nothing'), (1, 'Sleep'), (2, 'Hibernate'), (8, 'Shut down'), (32, 'Lock screen')]
SUPPLY = Path('/sys/class/power_supply')
THRESHOLD_FILES = ('charge_control_end_threshold', 'charge_stop_threshold')
LOGIND_DROPIN = Path('/etc/systemd/logind.conf.d/50-makos-lid.conf')


def current_profile():
    res = sysutil.run(['powerprofilesctl', 'get'])
    return res.out if res.code == 0 else None


def profiles():
    res = sysutil.run(['powerprofilesctl', 'list'])
    names = [n for n, _t in PROFILES if n in res.out] if res.code == 0 else []
    return {'available': names, 'current': current_profile()}


def set_profile(name):
    if name not in dict(PROFILES):
        raise ValueError('Unknown power profile.')
    if sysutil.run(['powerprofilesctl', 'set', name]).code != 0:
        raise RuntimeError('The power profiles service refused the change.')
    return current_profile()


def battery():
    res = sysutil.run(['busctl', '--system', '-j', 'call', 'org.freedesktop.UPower', '/org/freedesktop/UPower/devices/DisplayDevice',
                       'org.freedesktop.DBus.Properties', 'GetAll', 's', 'org.freedesktop.UPower.Device'])
    if res.code != 0:
        return None
    try:
        p = _unwrap(json.loads(res.out)['data'][0])
    except (ValueError, KeyError, IndexError):
        return None
    if not p.get('IsPresent', True):
        return None
    state = {1: 'charging', 2: 'discharging', 4: 'full', 5: 'pending charge'}.get(p.get('State'), 'unknown')
    return {'percent': round(p.get('Percentage', 0)), 'state': state, 'time_to_empty': int(p.get('TimeToEmpty', 0)),
            'time_to_full': int(p.get('TimeToFull', 0)), 'health': battery_health()}


def battery_health(base=SUPPLY):
    for b in sorted(base.glob('BAT*')) if base.exists() else []:
        try:
            full = int((b / 'energy_full').read_text() if (b / 'energy_full').exists() else (b / 'charge_full').read_text())
            design = int((b / 'energy_full_design').read_text() if (b / 'energy_full_design').exists() else (b / 'charge_full_design').read_text())
            return round(100 * full / design) if design else None
        except (OSError, ValueError):
            continue
    return None


def duration(seconds):
    if not seconds:
        return ''
    h, m = divmod(int(seconds) // 60, 60)
    return f'{h} h {m:02d} min' if h else f'{m} min'


def threshold(base=SUPPLY):
    for b in sorted(base.glob('BAT*')) if base.exists() else []:
        for name in THRESHOLD_FILES:
            f = b / name
            if f.exists():
                try:
                    return {'supported': True, 'value': int(f.read_text())}
                except (OSError, ValueError):
                    return {'supported': True, 'value': 100}
    return {'supported': False, 'value': 100}


def set_threshold(value):
    value = int(value)
    if not 50 <= value <= 100:
        raise ValueError('The charge limit must be between 50% and 100%.')
    return rootcall.call('battery-threshold', value)


def lid_action(path=LOGIND_DROPIN):
    """The lid action MakOS has configured (from its logind drop-in, readable by everyone); '' = distribution default."""
    try:
        for line in path.read_text().splitlines():
            if line.startswith('HandleLidSwitch='):
                return line.split('=', 1)[1].strip()
    except OSError:
        pass
    return ''


def set_lid_action(value):
    if value not in dict(LID_CHOICES):
        raise ValueError('Unknown lid action.')
    return rootcall.call('lid-action', value)


def powerdevil_running():
    res = sysutil.run(['busctl', '--user', 'status', 'org.kde.Solid.PowerManagement'])
    return res.code == 0


# powerdevilrc: [AC|Battery|LowBattery][SuspendAndShutdown] AutoSuspendAction, AutoSuspendIdleTimeoutSec; [..][Display] TurnOffDisplay*
def _grp(source, section):
    return f'{source}][{section}'


def power_options(source='AC'):
    ss, disp = _grp(source, 'SuspendAndShutdown'), _grp(source, 'Display')
    return {'idle_action': int(sysutil.kread('powerdevilrc', ss, 'AutoSuspendAction', '1') or 1),
            'idle_minutes': max(1, int(sysutil.kread('powerdevilrc', ss, 'AutoSuspendIdleTimeoutSec', '900') or 900) // 60),
            'screen_off_minutes': max(1, int(sysutil.kread('powerdevilrc', disp, 'TurnOffDisplayIdleTimeoutSec', '300') or 300) // 60)}


def set_power_options(source='AC', idle_action=None, idle_minutes=None, screen_off_minutes=None):
    if source not in ('AC', 'Battery', 'LowBattery'):
        raise ValueError('source must be AC, Battery or LowBattery')
    if not powerdevil_running():
        raise RuntimeError('The power management service is not running in this session, so idle actions cannot be applied.')
    ss, disp = _grp(source, 'SuspendAndShutdown'), _grp(source, 'Display')
    if idle_action is not None:
        if int(idle_action) not in {v for v, _t in ACTIONS}:
            raise ValueError('unknown power action')
        sysutil.kwrite('powerdevilrc', ss, 'AutoSuspendAction', int(idle_action))
    if idle_minutes is not None:
        sysutil.kwrite('powerdevilrc', ss, 'AutoSuspendIdleTimeoutSec', max(1, min(720, int(idle_minutes))) * 60)
    if screen_off_minutes is not None:
        sysutil.kwrite('powerdevilrc', disp, 'TurnOffDisplayIdleTimeoutSec', max(1, min(720, int(screen_off_minutes))) * 60)
        sysutil.kwrite('powerdevilrc', disp, 'TurnOffDisplayWhenIdle', True)
    sysutil.run(['busctl', '--user', 'call', 'org.kde.Solid.PowerManagement', '/org/kde/Solid/PowerManagement', 'org.kde.Solid.PowerManagement',
                 'reparseConfiguration'])
    return power_options(source)
