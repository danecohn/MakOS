# Adapted for MakkOS from Amerika OS (src/os/amerika/datetime_.py), GPL-3.0-only, Amerika LLC; MakkOS adaptations.
"""Date & time backend: systemd-timedated through `timedatectl` (its own polkit actions authorise changes)."""
import re

from .. import common
from . import sysutil

TZ_OK = re.compile(r'^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}$')


def status():
    res = sysutil.run(['timedatectl', 'show'])
    kv = sysutil.parse_kv(res.out)
    return {'available': res.code == 0, 'timezone': kv.get('Timezone', ''), 'ntp': kv.get('NTP') == 'yes', 'can_ntp': kv.get('CanNTP') == 'yes',
            'synchronized': kv.get('NTPSynchronized') == 'yes', 'local_rtc': kv.get('LocalRTC') == 'yes', 'time': kv.get('TimeUSec', ''),
            'clock_24h': bool(common.load_settings().get('clock_24h'))}


def timezones():
    res = sysutil.run(['timedatectl', 'list-timezones'], timeout=8)
    return res.out.splitlines() if res.code == 0 else []


def set_timezone(tz):
    if not TZ_OK.match(tz or ''):
        raise ValueError('Invalid time zone.')
    zones = timezones()
    if zones and tz not in zones:
        raise ValueError('Unknown time zone.')
    return sysutil.run(['timedatectl', 'set-timezone', tz], timeout=20).code == 0


def set_ntp(on):
    return sysutil.run(['timedatectl', 'set-ntp', 'true' if on else 'false'], timeout=20).code == 0


def set_time(text):
    """Set the clock by hand (needs automatic time off). text: 'YYYY-MM-DD HH:MM[:SS]'."""
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?', text or ''):
        raise ValueError('Use the form 2026-10-21 14:30.')
    return sysutil.run(['timedatectl', 'set-time', text], timeout=20).code == 0


def set_24h(on):
    s = common.load_settings()
    s['clock_24h'] = bool(on)
    common.save_settings(s)
    return bool(on)
