"""MakkOS owns its configuration; importing this module never writes any files."""
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
            'pins': ['files', 'venture', 'paper', 'digits', 'notes', 'terminal', 'settings', 'trash-empty'],
            # --- settings-and-Seek engineer: keys written by makos.settings panes (validated in settings.model.clean) ---
            'accent': 'blossom', 'font_size': 12, 'scrollbars': 'auto', 'reduce_transparency': False,
            'wallpaper': '', 'launcher_magnify': True, 'launcher_magnify_percent': 55, 'launcher_recents': False,
            'hot_corners': {}, 'text_replacements': [], 'clock_24h': False, 'text_scale': 1.0, 'high_contrast': False,
            'privacy_indicators': True, 'seek_exclusions': [], 'seek_web_engine': 'duckduckgo',
            # --- launcher-and-windows engineer: validated in shell/prefs.py (clean_launcher_prefs) ---
            'launcher_style': 'glass', 'launcher_folders': ['downloads', 'documents'], 'folder_views': {}, 'launcher_hot_edge': True,
            'window_memory': True, 'gestures': {}, 'switcher_hold_ms': 350}


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
    from .settings import model  # validates the settings-pane keys; no GTK import
    model.clean(data)
    from .shell import prefs as launcher_prefs  # launcher/window keys; pure Python
    launcher_prefs.clean(data)
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
