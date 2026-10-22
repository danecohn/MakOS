"""Launcher-and-windows checks, run inside makos_launcher_rig.sh (private D-Bus + KWin virtual output 1920x1080).

Real input goes through KWin's EIS endpoint (makos_input.py): pointer motion, clicks, drags and key chords reach the
shell exactly as a mouse and keyboard would. Screenshots are compositor captures in dist/makos/rig-launcher/ and are
meant to be looked at; the assertions cover state, files and timing. Select sections with MAKOS_CHECKS=dock,spread,...
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import makos_launcher_lib as L  # noqa: E402
from makos_input import BTN_RIGHT, Input  # noqa: E402

CFG = Path(os.environ['XDG_CONFIG_HOME']) / 'makos'
HOME = Path(os.environ['HOME'])
SCREEN_W, SCREEN_H, BAR_H = 1920, 1080, 28
RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print(('PASS ' if ok else 'FAIL ') + name + (' -- ' + str(detail) if detail else ''), flush=True)


def write_prefs(**values):
    CFG.mkdir(parents=True, exist_ok=True)
    path = CFG / 'settings.json'
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data.update(values)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def prefs_on_disk():
    try:
        return json.loads((CFG / 'settings.json').read_text())
    except (OSError, ValueError):
        return {}


def origin(st):
    """Screen position of the dock surface's top-left corner (bottom: centred on the bottom edge; sides: centred in the
    work area below the menu bar)."""
    sw, sh = st['surface']
    if st['pos'] == 'bottom':
        return ((SCREEN_W - sw) / 2.0, SCREEN_H - sh)
    y = BAR_H + (SCREEN_H - BAR_H - sh) / 2.0
    return (0.0, y) if st['pos'] == 'left' else (SCREEN_W - sw, y)


def item(st, key):
    return next(i for i in st['items'] if i['key'] == key)


def center(st, key):
    ox, oy = origin(st)
    x, y, w, h = item(st, key)['rect']
    return (ox + x + w / 2.0, oy + y + h / 2.0)


def settle(seconds=0.6):
    time.sleep(seconds)


def wait_state(pred, timeout=6, what='dock state'):
    end = time.monotonic() + timeout
    st = None
    while time.monotonic() < end:
        st = L.dockstate()
        if pred(st):
            return st
        time.sleep(0.15)
    raise AssertionError('timed out waiting for ' + what + ': ' + json.dumps({k: v for k, v in (st or {}).items() if k != 'items'}))


# ------------------------------------------------------------------------------------------------ sections
def section_dock(inp):
    notes = L.spawn_window('org.makos.Apps.notes', 'Notes rig window', '#c9a227')
    L.spawn_window('org.example.Scratch', 'Scratch rig window', '#7a4aa0')
    L.wait_for(lambda: L.window_by_title('Notes rig'), 15, 'notes window')
    L.wait_for(lambda: L.window_by_title('Scratch rig'), 15, 'scratch window')
    st = wait_state(lambda s: any(i['key'].startswith('x:') for i in s['items']), what='unpinned running app item')
    check('dock: running pinned app is marked running', item(st, 'notes')['running'])
    check('dock: running foreign app appears after the pinned apps', any(i['key'] == 'x:org.example.scratch' for i in st['items']),
          [i['key'] for i in st['items']])
    check('dock: Downloads and Documents stacks are present', {'downloads', 'documents'} <= {i['key'] for i in st['items']})
    check('dock: Trash is the last item', st['items'][-1]['kind'] == 'trash')
    # --- magnification, real pointer, glass style
    cx, cy = center(st, 'terminal')
    inp.move(cx - 300, cy, steps=8, duration=0.15)
    inp.move(cx, cy, steps=12, duration=0.25)
    settle(0.7)
    hover = L.dockstate()
    sizes = [round(i['length']) for i in hover['items'] if i['kind'] != 'separator']
    check('dock: Gaussian magnification peaks under the pointer', max(sizes) >= hover['base'] * 1.45 and
          item(hover, 'terminal')['length'] == max(i['length'] for i in hover['items']), sizes)
    check('dock: far items stay at rest size', min(sizes) == hover['base'], sizes)
    L.shot('dock-glass-hover')
    # --- frame times while sweeping the pointer across the bar
    L.control('rig:frames:start')
    ox, oy = origin(hover)
    left, right = ox + 40, ox + hover['surface'][0] - 40
    for _ in range(3):
        inp.move(right, cy, steps=60, duration=0.9)
        inp.move(left, cy, steps=60, duration=0.9)
    L.control('rig:frames:stop')
    settle(0.3)
    frames = json.loads((L.SHOTS / 'frames.json').read_text())
    (L.SHOTS / 'dock-frame-times.json').write_text(json.dumps({**frames, 'scope': 'virtual KWin output; not a physical 60 fps measurement'}, indent=1))
    check('dock: frame times while magnifying (virtual output)', frames['frames'] > 100 and frames['p95_ms'] < 25, frames)
    inp.move(960, 400, steps=10, duration=0.2)
    settle(0.8)
    check('dock: magnification returns to rest when the pointer leaves', max(i['length'] for i in L.dockstate()['items']) == hover['base'])
    # --- 3D shelf (settings change applies live)
    write_prefs(launcher_style='shelf3d')
    st3 = wait_state(lambda s: s['style'] == 'shelf3d', what='3d style applied live')
    cx, cy = center(st3, 'files')
    inp.move(cx + 260, cy, steps=10, duration=0.2)
    inp.move(cx + 60, cy, steps=10, duration=0.2)
    settle(0.8)
    L.shot('dock-3d-hover')
    inp.move(960, 400, steps=6, duration=0.1)
    write_prefs(launcher_style='glass')
    wait_state(lambda s: s['style'] == 'glass')
    return notes


def section_run(names):
    inp = Input()
    sections = {'dock': section_dock}
    for name in names:
        try:
            sections[name](inp)
        except Exception:
            traceback.print_exc()
            check(name + ': section completed', False, traceback.format_exc().splitlines()[-1])


def main():
    names = os.environ.get('MAKOS_CHECKS', 'dock').split(',')
    try:
        L.start_shell({'MAKOS_DEBUG_DOCK': '1'} if os.environ.get('MAKOS_DEBUG_DOCK') else None)
        time.sleep(1)
        section_run(names)
    finally:
        L.cleanup()
    log = Path(os.environ['T']) / 'makos-shell.log'
    text = log.read_text() if log.exists() else ''
    bad = [l for l in text.splitlines() if 'Traceback' in l or 'CRITICAL' in l or 'BUG' in l or 'CSS parser error' in l]
    check('shell log has no Traceback/CRITICAL/BUG', not bad, bad[:3])
    Path(L.SHOTS / 'shell.log').write_text(text)
    failed = [r for r in RESULTS if not r[1]]
    print('\nLAUNCHER CHECKS: %d passed, %d failed' % (len(RESULTS) - len(failed), len(failed)), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
