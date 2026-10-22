"""MakOS owns its configuration; importing this module never writes any files."""
import json
import os
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
SHARE = Path(os.environ.get('MAKOS_SHARE', SOURCE if (SOURCE / 'theme').exists() else '/usr/share/makos'))
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'makos'
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'makos'
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / 'makos'
DEFAULTS = {'launcher_size': 56, 'launcher_position': 'bottom', 'launcher_autohide': False,
            'reduce_motion': False, 'graphite': False, 'pinstripes': False,
            'pins': ['files', 'venture', 'paper', 'digits', 'notes', 'terminal', 'settings', 'trash-empty']}


def load_settings():
    data = dict(DEFAULTS)
    try:
        raw = json.loads((CONFIG / 'settings.json').read_text())
        if isinstance(raw, dict):
            data.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    try:
        data['launcher_size'] = max(32, min(96, int(data['launcher_size'])))
    except (ValueError, TypeError):
        data['launcher_size'] = 56
    if data['launcher_position'] not in ('bottom', 'left', 'right'):
        data['launcher_position'] = 'bottom'
    if not isinstance(data['pins'], list) or not all(isinstance(x, str) for x in data['pins']):
        data['pins'] = list(DEFAULTS['pins'])
    return data


def save_settings(data):
    CONFIG.mkdir(parents=True, exist_ok=True)
    path = CONFIG / 'settings.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({k: v for k, v in data.items() if k in DEFAULTS}, indent=2) + '\n')
    temp.chmod(0o600)
    temp.replace(path)
