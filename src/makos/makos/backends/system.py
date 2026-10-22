"""Thin, dependency-free wrappers around the system services the shell and the AI layer control.

Everything uses fixed argument lists (never a shell) and short timeouts.
"""
import json
import os
import re
import subprocess
from pathlib import Path


def _run(argv, timeout=3):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout.strip(), out.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, '', str(error)


# ----------------------------------------------------------------- audio (PipeWire via wpctl)
def volume():
    code, out, _ = _run(['wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@'])
    m = re.search(r'([0-9.]+)', out)
    if code or not m:
        return None
    return {'percent': round(float(m.group(1)) * 100), 'muted': 'MUTED' in out}


def set_volume(percent):
    percent = max(0, min(150, int(percent)))
    _run(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', f'{percent}%'])
    return volume()


def set_mute(muted):
    _run(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '1' if muted else '0'])
    return volume()


# ----------------------------------------------------------------- brightness (sysfs read, logind write)
def _backlight():
    base = Path('/sys/class/backlight')
    for d in sorted(base.glob('*')) if base.exists() else []:
        try:
            return d.name, int((d / 'brightness').read_text()), int((d / 'max_brightness').read_text())
        except (OSError, ValueError):
            continue
    return None


def brightness():
    b = _backlight()
    return None if not b else {'percent': round(100 * b[1] / max(1, b[2]))}


def set_brightness(percent):
    b = _backlight()
    if not b:
        return None
    value = max(1, round(max(1, min(100, int(percent))) / 100 * b[2]))
    _run(['busctl', 'call', 'org.freedesktop.login1', '/org/freedesktop/login1/session/auto',
          'org.freedesktop.login1.Session', 'SetBrightness', 'ssu', 'backlight', b[0], str(value)])
    return brightness()


# ----------------------------------------------------------------- battery (UPower)
def battery():
    code, out, _ = _run(['busctl', '--system', '-j', 'call', 'org.freedesktop.UPower',
                         '/org/freedesktop/UPower/devices/DisplayDevice', 'org.freedesktop.DBus.Properties', 'GetAll',
                         's', 'org.freedesktop.UPower.Device'])
    if code:
        return None
    try:
        data = json.loads(out)['data'][0]
        pct = round(data['Percentage']['data'])
        state = {1: 'charging', 2: 'discharging', 4: 'full', 5: 'pending-charge'}.get(data['State']['data'], 'unknown')
        present = data.get('IsPresent', {}).get('data', True)
        seconds = data.get('TimeToEmpty' if state == 'discharging' else 'TimeToFull', {}).get('data', 0)
        remaining = f'{seconds//3600}h {(seconds%3600)//60}m remaining' if seconds > 0 else None
        return {'percent': pct, 'state': state, 'present': present, 'remaining': remaining}
    except (KeyError, ValueError, IndexError):
        return None


# ----------------------------------------------------------------- network (NetworkManager via nmcli)
def network():
    code, out, _ = _run(['nmcli', '-t', '-f', 'TYPE,STATE,CONNECTION', 'device'])
    if code:
        return {'state': 'unknown', 'connection': None}
    for line in out.splitlines():
        t, state, conn = (line.split(':') + ['', '', ''])[:3]
        if state == 'connected' and t in ('wifi', 'ethernet'):
            return {'state': 'connected', 'type': t, 'connection': conn}
    wifi = _run(['nmcli', 'radio', 'wifi'])[1]
    return {'state': 'disconnected', 'wifi': wifi}


def wifi_enabled():
    return _run(['nmcli', 'radio', 'wifi'])[1] == 'enabled'


def set_wifi(on):
    _run(['nmcli', 'radio', 'wifi', 'on' if on else 'off'])
    return wifi_enabled()


# ----------------------------------------------------------------- power profiles
def power_profile():
    code, out, _ = _run(['powerprofilesctl', 'get'])
    return out if not code else None


def set_power_profile(name):
    if name not in ('power-saver', 'balanced', 'performance'):
        raise ValueError('profile must be power-saver, balanced or performance')
    _run(['powerprofilesctl', 'set', name])
    return power_profile()


# ----------------------------------------------------------------- displays (kscreen-doctor against KWin)
def displays():
    code, out, _ = _run(['kscreen-doctor', '-j'], 5)
    if code:
        return []
    try:
        return [{'name': o['name'], 'enabled': o['enabled'], 'scale': o['scale'], 'width': o['size']['width'],
                 'height': o['size']['height']} for o in json.loads(out)['outputs']]
    except (KeyError, ValueError):
        return []


def set_display_scale(output, scale):
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,32}', output):
        raise ValueError('invalid output name')
    scale = float(scale)
    if not 0.5 <= scale <= 4:
        raise ValueError('scale must be between 0.5 and 4')
    _run(['kscreen-doctor', f'output.{output}.scale.{scale}'], 8)
    return displays()


# ----------------------------------------------------------------- session power (logind)
def power_action(action):
    method = {'suspend': 'Suspend', 'reboot': 'Reboot', 'poweroff': 'PowerOff', 'hibernate': 'Hibernate'}.get(action)
    if not method:
        raise ValueError('unknown power action')
    _run(['busctl', 'call', 'org.freedesktop.login1', '/org/freedesktop/login1', 'org.freedesktop.login1.Manager',
          method, 'b', 'true'], 10)


def lock_session():
    _run(['loginctl', 'lock-session'])


def logout():
    sid = os.environ.get('XDG_SESSION_ID')
    if sid and re.fullmatch(r'[A-Za-z0-9_-]{1,20}', sid):
        _run(['loginctl', 'terminate-session', sid])


def uptime_seconds():
    try:
        return int(float(Path('/proc/uptime').read_text().split()[0]))
    except (OSError, ValueError):
        return None


def os_info():
    data = {}
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                data[k] = v.strip('"')
    except OSError:
        pass
    return {'distribution': data.get('PRETTY_NAME'), 'kernel': os.uname().release, 'machine': os.uname().machine,
            'host': os.uname().nodename, 'uptime_seconds': uptime_seconds()}
