# Adapted for MakkOS from Amerika OS (src/os/amerika/shortcuts.py), GPL-3.0-only, Amerika LLC; MakkOS adaptations.
"""Global shortcut editor backend.

The shortcut *definitions* come from bridge/bridge.js (`registerShortcut(title, description, default, ...)`); the
*current* keys live in KDE's global-accelerator store (kglobalshortcutsrc, component "kwin"). Changes go through
org.kde.KGlobalAccel over D-Bus, so they apply immediately and persist. Conflicts are checked against every other
MakkOS shortcut and every shortcut KDE has registered.
"""
import re
from pathlib import Path

from .. import common
from . import sysutil

BRIDGE = common.SHARE / 'bridge' / 'bridge.js'
COMPONENT = 'kwin'
COMPONENT_NAME = 'KWin'
# bridge.js registers shortcuts through registerShortcut(...) and its wrappers act(...) / key(...); the snap zones come from a table
PREFIX = 'MakOS: '
# bridge.js registers shortcuts through key('Name', 'Meta+Space', ...). The two tiling shortcuts come from a forEach over the sides.
_REG = re.compile(r"""\bkey\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]*)['"]""")
_SIDES = re.compile(r"""\[\s*'Left'\s*,\s*'Right'\s*\]\.forEach""")


MODS = {'shift': 0x02000000, 'ctrl': 0x04000000, 'alt': 0x08000000, 'meta': 0x10000000}
NAMED = {'backtab': 0x01000002, 'volumedown': 0x01000070, 'volumemute': 0x01000071, 'volumeup': 0x01000072, 'mediaplay': 0x01000080,
         'mediastop': 0x01000081, 'mediaprevious': 0x01000082, 'medianext': 0x01000083,
         'escape': 0x01000000, 'esc': 0x01000000, 'tab': 0x01000001, 'backspace': 0x01000003, 'return': 0x01000004, 'enter': 0x01000005,
         'insert': 0x01000006, 'delete': 0x01000007, 'pause': 0x01000008, 'print': 0x01000009, 'home': 0x01000010, 'end': 0x01000011,
         'left': 0x01000012, 'up': 0x01000013, 'right': 0x01000014, 'down': 0x01000015, 'pageup': 0x01000016, 'pagedown': 0x01000017,
         'space': 0x20}
MODONLY = {'shift': 0x01000020, 'ctrl': 0x01000021, 'meta': 0x01000022, 'alt': 0x01000023}
ALIASES = {'super': 'meta', 'win': 'meta', 'windows': 'meta', 'control': 'ctrl', 'escape': 'escape'}
ORDER = ['meta', 'ctrl', 'alt', 'shift']


def definitions(text=None):
    """[{'id': 'MakOS: Name', 'title', 'description', 'default'}] from bridge.js."""
    if text is None:
        try:
            text = BRIDGE.read_text(encoding='utf-8')
        except OSError:
            return []
    out, seen = [], set()

    def add(name, default):
        title = PREFIX + name
        if title not in seen:
            seen.add(title)
            out.append({'id': title, 'title': name, 'description': name, 'default': normalise(default)})
    for name, default in _REG.findall(text):
        if name.startswith("Tile '"):
            continue
        add(name, default)
    if _SIDES.search(text):
        for side in ('Left', 'Right'):
            add('Tile ' + side, 'Meta+' + side)
    # anything else the running session registered under the MakkOS prefix (default = second field of the store entry)
    for action, (_keys, default) in read_store_full().get(COMPONENT, {}).items():
        if action.startswith(PREFIX):
            add(action[len(PREFIX):], default)
    return out


def normalise(seq):
    """Canonical text for a key sequence: 'super+shift+f23' -> 'Meta+Shift+F23'. Empty / 'none' -> ''."""
    seq = (seq or '').strip()
    if not seq or seq.lower() == 'none':
        return ''
    parts = [p.strip() for p in seq.replace(' ', '').split('+') if p.strip()]
    if seq.endswith('++'):
        parts.append('+')
    mods, key = set(), ''
    for p in parts:
        low = ALIASES.get(p.lower(), p.lower())
        if low in MODS:
            mods.add(low)
        else:
            key = p
    out = [m.capitalize() for m in ORDER if m in mods]
    if key:
        k = NAMED_DISPLAY.get(key.lower(), key.upper() if len(key) == 1 else key)
        if re.fullmatch(r'[fF]\d{1,2}', key):
            k = key.upper()
        out.append(k)
    return '+'.join(out)


NAMED_DISPLAY = {'escape': 'Escape', 'esc': 'Escape', 'pageup': 'PgUp', 'pgup': 'PgUp', 'pagedown': 'PgDown', 'pgdown': 'PgDown', 'return': 'Return',
                 'enter': 'Enter', 'space': 'Space', 'tab': 'Tab', 'backspace': 'Backspace', 'delete': 'Del', 'del': 'Del', 'insert': 'Ins',
                 'ins': 'Ins', 'home': 'Home', 'end': 'End', 'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down', 'print': 'Print',
                 'pause': 'Pause'}


def valid(seq):
    seq = normalise(seq)
    if not seq:
        return True
    try:
        qt_encode(seq)
        return True
    except ValueError:
        return False


def qt_encode(seq):
    """Qt key code (what KGlobalAccel's D-Bus API takes) for a normalised sequence."""
    seq = normalise(seq)
    if not seq:
        return 0
    parts = seq.split('+') if not seq.endswith('+') else seq[:-1].split('+') + ['+']
    code = 0
    key = None
    for p in parts:
        low = p.lower()
        if low in MODS and p is not parts[-1]:
            code |= MODS[low]
        else:
            key = p
    if key is None:
        raise ValueError('incomplete shortcut')
    low = key.lower()
    if low in MODS:  # a modifier on its own (e.g. the Windows key tap)
        return MODONLY[low]
    if low in NAMED:
        return code | NAMED[low]
    alias = {'pgup': 'pageup', 'pgdown': 'pagedown', 'del': 'delete', 'ins': 'insert'}.get(low)
    if alias:
        return code | NAMED[alias]
    m = re.fullmatch(r'f(\d{1,2})', low)
    if m and 1 <= int(m.group(1)) <= 35:
        return code | (0x01000030 + int(m.group(1)) - 1)
    if len(key) == 1 and 0x20 <= ord(key.upper()) < 0x7f:
        if code & MODS['shift'] and not key.isalnum():
            raise ValueError('Shift with a symbol key is ambiguous; choose another key.')
        return code | ord(key.upper())
    raise ValueError(f'unknown key "{key}"')


def _rc_path():
    """kglobalacceld stores shortcuts in the XDG_CONFIG_HOME it was started with. Depending on how it was activated that is the
    compositor's private directory or the user's: read whichever exists (the newer one when both do)."""
    paths = [sysutil.compositor_home() / 'kglobalshortcutsrc', sysutil.config_home() / 'kglobalshortcutsrc']
    found = [p for p in paths if p.exists()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else paths[0]


def read_store():
    """{component: {action: [current keys]}} parsed from kglobalshortcutsrc."""
    return {c: {a: v[0] for a, v in acts.items()} for c, acts in read_store_full().items()}


def read_store_full():
    """{component: {action: ([current keys], default)}} parsed from kglobalshortcutsrc."""
    out, group = {}, None
    try:
        lines = _rc_path().read_text(encoding='utf-8').splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.rstrip('\n')
        if line.startswith('[') and line.endswith(']'):
            group = line[1:-1]
            out.setdefault(group, {})
        elif '=' in line and group is not None:
            k, v = line.split('=', 1)
            fields = v.split(',')
            cur = fields[0]
            keys = [normalise(s) for s in re.split(r'\\t|\t', cur) if normalise(s)]
            default = normalise(re.split(r'\\t|\t', fields[1])[0]) if len(fields) > 1 else ''
            out[group][k] = (keys, default)
    return out


def current(title):
    store = read_store().get(COMPONENT, {})
    if title in store:
        return store[title][0] if store[title] else ''
    default = next((d['default'] for d in definitions() if d['id'] == title), '')
    return default


def listing():
    """Every MakkOS shortcut with its current and default keys and its conflicts."""
    store = read_store()
    defs = definitions()
    cur_map = {d['id']: (store.get(COMPONENT, {}).get(d['id'], None)) for d in defs}
    out = []
    for d in defs:
        cur = (cur_map[d['id']][0] if cur_map[d['id']] else '') if cur_map[d['id']] is not None else d['default']
        out.append({**d, 'current': cur, 'modified': cur != d['default'], 'editable': valid(d['default']) and bool(d['default'])})
    for item in out:
        item['conflicts'] = conflicts(item['id'], item['current'], store=store, current_override={i['id']: i['current'] for i in out})
    return out


def conflicts(title, seq, store=None, current_override=None):
    """Other actions that already use `seq` ([{'component','action'}])."""
    seq = normalise(seq)
    if not seq:
        return []
    store = store if store is not None else read_store()
    found = []
    mine = {d['id'] for d in definitions()}
    for comp, actions in store.items():
        if comp.startswith('$') or comp in ('ActivityManager',):
            continue
        for action, keys in actions.items():
            if comp == COMPONENT and action in mine:
                continue  # MakkOS actions are checked against their live values below
            if seq in keys and not (comp == COMPONENT and action == title):
                found.append({'component': comp, 'action': action})
    live = current_override or {d['id']: current(d['id']) for d in definitions()}
    for action, key in live.items():
        if action != title and key == seq:
            found.append({'component': 'MakkOS', 'action': action})
    return found


def set_shortcut(title, seq, allow_conflict=False):
    """Change one MakkOS shortcut. Raises ValueError for unknown actions, bad keys or (unless allowed) conflicts."""
    if title not in {d['id'] for d in definitions()}:
        raise ValueError('Unknown shortcut.')
    seq = normalise(seq)
    if not valid(seq):
        raise ValueError('That key combination cannot be used.')
    clash = conflicts(title, seq)
    if clash and not allow_conflict:
        names = ', '.join(f"{c['action']} ({c['component']})" for c in clash[:3])
        raise ValueError(f'{seq} is already used by {names}.')
    code = qt_encode(seq) if seq else 0
    res = sysutil.run(['busctl', '--user', 'call', 'org.kde.kglobalaccel', '/kglobalaccel', 'org.kde.KGlobalAccel', 'setShortcutKeys',
                       'asa(ai)u', '4', COMPONENT, title, COMPONENT_NAME, title, '1' if seq else '0'] +
                      (['4', str(code), '0', '0', '0'] if seq else []) + ['6'], timeout=8)
    if res.code != 0:
        raise RuntimeError('The shortcut service did not accept the change.')
    return seq


def reset(title):
    default = next((d['default'] for d in definitions() if d['id'] == title), None)
    if default is None:
        raise ValueError('Unknown shortcut.')
    return set_shortcut(title, default, allow_conflict=True)
