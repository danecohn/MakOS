"""Files preferences (view, sort, hidden files, saved servers). Stored in ~/.config/makos/files.json."""
import json

from .. import common

DEFAULTS = {'view': 'icons', 'icon_size': 64, 'sort_key': 'name', 'sort_reverse': False, 'show_hidden': False,
            'folders_first': True, 'servers': [], 'width': 1040, 'height': 680, 'sidebar_width': 196}
VIEWS = ('icons', 'list', 'columns', 'cover')


def load():
    data = dict(DEFAULTS)
    try:
        raw = json.loads((common.CONFIG / 'files.json').read_text())
        if isinstance(raw, dict):
            data.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if data['view'] not in VIEWS:
        data['view'] = 'icons'
    try:
        data['icon_size'] = max(32, min(160, int(data['icon_size'])))
    except (TypeError, ValueError):
        data['icon_size'] = 64
    from .model import SORT_KEYS
    if data['sort_key'] not in SORT_KEYS:
        data['sort_key'] = 'name'
    data['sort_reverse'] = bool(data['sort_reverse'])
    data['show_hidden'] = bool(data['show_hidden'])
    data['folders_first'] = bool(data['folders_first'])
    if not isinstance(data['servers'], list) or not all(isinstance(s, str) for s in data['servers']):
        data['servers'] = []
    return data


def save(data):
    try:
        common.CONFIG.mkdir(parents=True, exist_ok=True)
        path = common.CONFIG / 'files.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps({k: v for k, v in data.items() if k in DEFAULTS}, indent=2) + '\n')
        temp.chmod(0o600)
        temp.replace(path)
    except OSError:
        pass
