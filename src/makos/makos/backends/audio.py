"""Sound settings backend: PipeWire/WirePlumber through `wpctl` and `pactl` (pipewire-pulse), JSON where available."""
import json
import math
import re
import struct
import tempfile
import wave
from pathlib import Path

from . import sysutil

NAME_OK = re.compile(r'^[A-Za-z0-9_.:+\-@]{1,200}$')


def _json(argv):
    res = sysutil.run(argv, timeout=6)
    if res.code != 0 or not res.out:
        return []
    try:
        return json.loads(res.out)
    except ValueError:
        return []


def _check_name(name):
    if not NAME_OK.match(name or ''):
        raise ValueError('Invalid audio device name.')
    return name


def _pct(volume):
    """Mean volume percentage of a pactl `volume` dict across channels."""
    vals = [v.get('value_percent', '0%').rstrip('%') for v in (volume or {}).values()]
    nums = [int(v) for v in vals if v.isdigit()]
    return round(sum(nums) / len(nums)) if nums else 0


def _balance(volume):
    vals = [int(v['value_percent'].rstrip('%')) for k, v in (volume or {}).items() if k in ('front-left', 'front-right') and v.get('value_percent', '').rstrip('%').isdigit()]
    if len(vals) == 2 and max(vals) > 0:
        left, right = vals
        return round((right - left) / max(left, right), 2)
    return 0.0


def default_name(kind):
    res = sysutil.run(['pactl', 'get-default-' + ('sink' if kind == 'output' else 'source')])
    return res.out if res.code == 0 else None


def devices(kind='output'):
    """kind: 'output' (sinks) or 'input' (sources, monitors excluded)."""
    plural = 'sinks' if kind == 'output' else 'sources'
    default = default_name(kind)
    out = []
    for d in _json(['pactl', '-f', 'json', 'list', plural]):
        if kind == 'input' and (d.get('monitor_source') == '' and d.get('name', '').endswith('.monitor') or d.get('properties', {}).get('device.class') == 'monitor'):
            continue
        ports = [{'name': p['name'], 'description': p.get('description', p['name']), 'available': p.get('availability', 'unknown') != 'not available'}
                 for p in d.get('ports', [])]
        out.append({'name': d['name'], 'description': d.get('description', d['name']), 'default': d['name'] == default,
                    'volume': _pct(d.get('volume')), 'muted': bool(d.get('mute')), 'balance': _balance(d.get('volume')),
                    'channels': len(d.get('volume', {})) or 2, 'active_port': d.get('active_port'), 'ports': ports,
                    'card': d.get('properties', {}).get('device.name') or d.get('card')})
    return out


def set_default(kind, name):
    res = sysutil.run(['pactl', 'set-default-' + ('sink' if kind == 'output' else 'source'), _check_name(name)])
    return res.code == 0


def _dev_cmd(kind):
    return 'sink' if kind == 'output' else 'source'


def set_volume(kind, name, percent):
    percent = max(0, min(150, int(percent)))
    return sysutil.run(['pactl', f'set-{_dev_cmd(kind)}-volume', _check_name(name), f'{percent}%']).code == 0


def set_mute(kind, name, muted):
    return sysutil.run(['pactl', f'set-{_dev_cmd(kind)}-mute', _check_name(name), '1' if muted else '0']).code == 0


def set_balance(name, balance, channels=2):
    """balance -1.0 (left) .. +1.0 (right); keeps the louder side at the current overall volume."""
    balance = max(-1.0, min(1.0, float(balance)))
    dev = next((d for d in devices('output') if d['name'] == name), None)
    if not dev:
        return False
    base = dev['volume']
    left = base if balance <= 0 else round(base * (1 - balance))
    right = base if balance >= 0 else round(base * (1 + balance))
    vols = [f'{left}%', f'{right}%'] + [f'{base}%'] * max(0, channels - 2)
    return sysutil.run(['pactl', 'set-sink-volume', _check_name(name)] + vols).code == 0


def set_port(kind, name, port):
    return sysutil.run(['pactl', f'set-{_dev_cmd(kind)}-port', _check_name(name), _check_name(port)]).code == 0


def apps():
    """Per-application playback streams."""
    out = []
    for s in _json(['pactl', '-f', 'json', 'list', 'sink-inputs']):
        props = s.get('properties', {})
        out.append({'index': s['index'], 'name': props.get('application.name') or props.get('media.name') or 'Unknown app',
                    'volume': _pct(s.get('volume')), 'muted': bool(s.get('mute')), 'icon': props.get('application.icon_name', '')})
    return out


def set_app_volume(index, percent):
    percent = max(0, min(150, int(percent)))
    return sysutil.run(['pactl', 'set-sink-input-volume', str(int(index)), f'{percent}%']).code == 0


def set_app_mute(index, muted):
    return sysutil.run(['pactl', 'set-sink-input-mute', str(int(index)), '1' if muted else '0']).code == 0


def mic_users():
    """Applications currently recording (for the microphone indicator)."""
    names = []
    for s in _json(['pactl', '-f', 'json', 'list', 'source-outputs']):
        props = s.get('properties', {})
        names.append(props.get('application.name') or props.get('media.name') or 'An app')
    return names


def cards():
    out = []
    for c in _json(['pactl', '-f', 'json', 'list', 'cards']):
        profiles = [{'name': n, 'description': p.get('description', n), 'available': p.get('available', True)}
                    for n, p in (c.get('profiles') or {}).items()]
        out.append({'name': c['name'], 'description': c.get('properties', {}).get('device.description') or c['name'],
                    'active_profile': c.get('active_profile'), 'profiles': profiles})
    return out


def set_profile(card, profile):
    return sysutil.run(['pactl', 'set-card-profile', _check_name(card), _check_name(profile)]).code == 0


def tone_file(channel='both', hz=440, seconds=1.2, rate=44100):
    """Write a short stereo sine tone WAV (left, right or both) and return its path."""
    path = Path(tempfile.mkdtemp(prefix='amerika-tone-')) / f'tone-{channel}.wav'
    n = int(rate * seconds)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            env = min(1, i / 2000, (n - i) / 2000)  # fade in/out: no clicks
            s = int(9000 * env * math.sin(2 * math.pi * hz * i / rate))
            frames += struct.pack('<hh', s if channel in ('both', 'left') else 0, s if channel in ('both', 'right') else 0)
        w.writeframes(bytes(frames))
    return path


def test_tone(name=None, channel='both'):
    if channel not in ('both', 'left', 'right'):
        raise ValueError('channel must be both, left or right')
    path = tone_file(channel)
    argv = ['paplay', str(path)] if sysutil.have('paplay') else ['pw-play', str(path)]
    if name and argv[0] == 'paplay':
        argv = ['paplay', f'--device={_check_name(name)}', str(path)]
    return sysutil.run(argv, timeout=10).code == 0
