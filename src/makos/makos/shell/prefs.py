"""Validation of the settings.json keys owned by the Launcher Bar / windows code. Pure Python (no GTK, no I/O).

`clean(data)` repairs a loaded settings dict in place so a hand-edited file can never crash the shell.
Keys: launcher_style ('glass' 2D shelf | 'shelf3d' perspective floor), launcher_folders (stack ids shown after the apps),
folder_views ({folder id: 'auto'|'fan'|'grid'}), launcher_hot_edge (reveal an auto-hidden bar from the screen edge),
window_memory (reopen windows where they were), gestures ({gesture name: action}), switcher_hold_ms (how long Meta+Tab is
held before the application strip appears).
"""
STYLES = ('glass', 'shelf3d')
FOLDER_IDS = ('downloads', 'documents', 'desktop', 'pictures', 'music')
VIEWS = ('auto', 'fan', 'grid')


def _int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def clean(data):
    if data.get('launcher_style') not in STYLES:
        data['launcher_style'] = 'glass'
    folders = data.get('launcher_folders')
    if isinstance(folders, list):
        seen = []
        for f in folders:
            if f in FOLDER_IDS and f not in seen:
                seen.append(f)
        data['launcher_folders'] = seen
    else:
        data['launcher_folders'] = ['downloads', 'documents']
    views = data.get('folder_views')
    data['folder_views'] = {k: v for k, v in views.items() if k in FOLDER_IDS and v in VIEWS} if isinstance(views, dict) else {}
    data['launcher_hot_edge'] = bool(data.get('launcher_hot_edge', True))
    data['window_memory'] = bool(data.get('window_memory', True))
    g = data.get('gestures')
    data['gestures'] = {k: v for k, v in g.items() if isinstance(k, str) and isinstance(v, str) and len(k) < 40 and len(v) < 40} if isinstance(g, dict) else {}
    data['switcher_hold_ms'] = _int(data.get('switcher_hold_ms'), 0, 2000, 350)
    return data
