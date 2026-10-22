"""Widgets layer settings: which widgets exist, where they sit, and each widget's own data."""
import json
import os
from pathlib import Path
from .. import common

KINDS = {'clock': 'Clock', 'weather': 'Weather', 'calculator': 'Calculator', 'notes': 'Notes', 'converter': 'Unit Converter',
         'calendar': 'Calendar', 'sysmon': 'System Monitor', 'worldclock': 'World Clocks'}
DEFAULT_LAYOUT = [('clock', 60, 80), ('calendar', 330, 80), ('weather', 620, 80), ('sysmon', 60, 330), ('worldclock', 330, 400), ('calculator', 620, 330), ('notes', 900, 80), ('converter', 900, 330)]
DEFAULT_ZONES = [{'label': 'New York', 'tz': 'America/New_York'}, {'label': 'London', 'tz': 'Europe/London'}, {'label': 'Tokyo', 'tz': 'Asia/Tokyo'}]
MAX_NOTE = 5000


def path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'makos' / 'widgets.json'


def default():
    return {'version': 1, 'widgets': [{'kind': k, 'x': x, 'y': y} for k, x, y in DEFAULT_LAYOUT[:6]],
            'weather': {'enabled': False, 'label': '', 'latitude': None, 'longitude': None, 'last': None},
            'zones': [dict(z) for z in DEFAULT_ZONES], 'notes': ''}


def clean(raw):
    out = default()
    if not isinstance(raw, dict):
        return out
    widgets, seen = [], set()
    for w in raw.get('widgets', []) if isinstance(raw.get('widgets'), list) else []:
        if isinstance(w, dict) and w.get('kind') in KINDS and w['kind'] not in seen:
            try:
                widgets.append({'kind': w['kind'], 'x': max(0, min(8000, int(w.get('x', 0)))), 'y': max(0, min(8000, int(w.get('y', 0))))})
                seen.add(w['kind'])
            except (TypeError, ValueError):
                pass
    if isinstance(raw.get('widgets'), list):
        out['widgets'] = widgets
    wx = raw.get('weather')
    if isinstance(wx, dict):
        lat, lon = wx.get('latitude'), wx.get('longitude')
        ok = isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180
        out['weather'] = {'enabled': bool(wx.get('enabled')) and ok, 'label': str(wx.get('label', ''))[:60], 'latitude': lat if ok else None, 'longitude': lon if ok else None,
                          'last': wx.get('last') if isinstance(wx.get('last'), dict) else None}
    zones = raw.get('zones')
    if isinstance(zones, list):
        good = [{'label': str(z.get('label', ''))[:30], 'tz': str(z.get('tz', ''))[:60]} for z in zones if isinstance(z, dict) and z.get('tz')][:6]
        out['zones'] = good or out['zones']
    if isinstance(raw.get('notes'), str):
        out['notes'] = raw['notes'][:MAX_NOTE]
    return out


def load(file=None):
    try:
        return clean(json.loads(Path(file or path()).read_text()))
    except (OSError, ValueError):
        return default()


def save(data, file=None):
    target = Path(file or path())
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(clean(data), indent=1) + '\n')
    temp.chmod(0o600)
    temp.replace(target)


def add_widget(data, kind, x=60, y=80):
    if kind in KINDS and not any(w['kind'] == kind for w in data['widgets']):
        data['widgets'].append({'kind': kind, 'x': x, 'y': y})
    return data


def remove_widget(data, kind):
    data['widgets'] = [w for w in data['widgets'] if w['kind'] != kind]
    return data


def move_widget(data, kind, x, y):
    for w in data['widgets']:
        if w['kind'] == kind:
            w['x'], w['y'] = max(0, int(x)), max(0, int(y))
    return data
