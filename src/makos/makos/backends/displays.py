"""Display settings backend: `kscreen-doctor` (libkscreen, talks to KWin) and KWin's NightLight D-Bus / kwinrc.

Verified shape of `kscreen-doctor -j` on Plasma 6: outputs[] with name, enabled, connected, modes[{id,size,refreshRate}],
currentModeId, scale, rotation (1 none, 2 left, 4 inverted, 8 right), pos, priority (1 = primary), and, on hardware that
supports them, hdr / wcg / sdrBrightness / brightness / vrrPolicy. Missing keys mean "not supported" and the UI hides them.
"""
import json
import re

from . import sysutil

ROTATIONS = {1: 'normal', 2: 'left', 4: 'inverted', 8: 'right'}
ROTATION_NAMES = {v: k for k, v in ROTATIONS.items()}
NAME_OK = re.compile(r'^[A-Za-z0-9._-]{1,32}$')
SCALES = [1.0, 1.25, 1.35, 1.5, 1.75, 2.0, 2.5, 3.0]


def _output(o, primary_priority=1):
    modes = [{'id': str(m['id']), 'width': m['size']['width'], 'height': m['size']['height'], 'refresh': round(float(m.get('refreshRate', 0)), 2)}
             for m in o.get('modes', [])]
    cur = next((m for m in modes if m['id'] == str(o.get('currentModeId'))), None)
    out = {'name': o['name'], 'enabled': bool(o.get('enabled')), 'connected': bool(o.get('connected', True)), 'scale': float(o.get('scale', 1)),
           'rotation': ROTATIONS.get(o.get('rotation', 1), 'normal'), 'x': o.get('pos', {}).get('x', 0), 'y': o.get('pos', {}).get('y', 0),
           'priority': o.get('priority', 0), 'primary': o.get('priority') == primary_priority, 'modes': modes, 'mode': cur,
           'width': (cur or {}).get('width') or o.get('size', {}).get('width', 0), 'height': (cur or {}).get('height') or o.get('size', {}).get('height', 0),
           'mm': (o.get('sizeMM', {}).get('width'), o.get('sizeMM', {}).get('height')),
           'hdr': o.get('hdr') if 'hdr' in o else None, 'wcg': o.get('wcg') if 'wcg' in o else None,
           'sdr_brightness': o.get('sdrBrightness'), 'brightness': o.get('brightness'), 'vrr': o.get('vrrPolicy')}
    # logical size after scale and rotation: what the arrangement canvas draws
    w, h = out['width'], out['height']
    if out['rotation'] in ('left', 'right'):
        w, h = h, w
    out['logical'] = (round(w / out['scale']), round(h / out['scale'])) if out['scale'] else (w, h)
    return out


def outputs():
    res = sysutil.run(['kscreen-doctor', '-j'], timeout=8)
    if res.code != 0 or not res.out:
        return []
    try:
        data = json.loads(res.out)['outputs']
    except (ValueError, KeyError):
        return []
    return [_output(o) for o in data if o.get('connected', True)]


def resolutions(out):
    """Distinct resolutions of an output, largest first."""
    seen = {}
    for m in out['modes']:
        seen.setdefault((m['width'], m['height']), []).append(m)
    return sorted(seen.items(), key=lambda kv: -kv[0][0] * kv[0][1])


def refresh_rates(out, width, height):
    return sorted({m['refresh'] for m in out['modes'] if (m['width'], m['height']) == (width, height)}, reverse=True)


def mode_for(out, width, height, refresh=None):
    cands = [m for m in out['modes'] if (m['width'], m['height']) == (width, height)]
    if not cands:
        raise ValueError('That resolution is not offered by this display.')
    if refresh is not None:
        best = min(cands, key=lambda m: abs(m['refresh'] - refresh))
    else:
        best = max(cands, key=lambda m: m['refresh'])
    return best


def _name(n):
    if not NAME_OK.match(n or ''):
        raise ValueError('invalid output name')
    return n


def apply(changes):
    """changes: list of (output, setting, value) applied in ONE kscreen-doctor call so they take effect atomically.

    Settings: mode (mode id), scale, rotation, position ('x,y'), primary (True), enabled, hdr, wcg, sdr_brightness, brightness, vrr.
    """
    args = []
    for out, setting, value in changes:
        name = _name(out)
        if setting == 'mode':
            if not re.fullmatch(r'[0-9]{1,4}', str(value)):
                raise ValueError('invalid mode id')
            args.append(f'output.{name}.mode.{value}')
        elif setting == 'scale':
            v = float(value)
            if not 0.5 <= v <= 4:
                raise ValueError('scale must be between 0.5 and 4')
            args.append(f'output.{name}.scale.{round(v, 2)}')
        elif setting == 'rotation':
            if value not in ROTATION_NAMES:
                raise ValueError('rotation must be normal, left, right or inverted')
            args.append(f'output.{name}.rotation.{"none" if value == "normal" else value}')
        elif setting == 'position':
            x, y = (int(p) for p in str(value).split(','))
            args.append(f'output.{name}.position.{x},{y}')
        elif setting == 'primary':
            args.append(f'output.{name}.priority.1')
        elif setting == 'enabled':
            args.append(f'output.{name}.{"enable" if value else "disable"}')
        elif setting in ('hdr', 'wcg'):
            args.append(f'output.{name}.{setting}.{"enable" if value else "disable"}')
        elif setting == 'sdr_brightness':
            args.append(f'output.{name}.sdr-brightness.{max(100, min(1000, int(value)))}')
        elif setting == 'brightness':
            args.append(f'output.{name}.brightness.{max(0, min(100, int(value)))}')
        elif setting == 'vrr':
            if value not in ('never', 'automatic', 'always'):
                raise ValueError('vrr must be never, automatic or always')
            args.append(f'output.{name}.vrrpolicy.{value}')
        else:
            raise ValueError(f'unknown display setting {setting}')
    if not args:
        return outputs()
    res = sysutil.run(['kscreen-doctor'] + args, timeout=15)
    if res.code != 0:
        raise RuntimeError(res.err or 'The display change was refused.')
    return outputs()


# ---------------------------------------------------------------- arrangement
def snap(moving, others, threshold=60):
    """Snap a dragged output's top-left (moving = {'x','y','logical'}) against the edges of the others so screens touch and never overlap."""
    w, h = moving['logical']
    x, y = moving['x'], moving['y']
    best = None
    for o in others:
        ow, oh = o['logical']
        ox, oy = o['x'], o['y']
        cands = [(ox + ow, y), (ox - w, y), (x, oy + oh), (x, oy - h)]  # right of, left of, below, above
        for cx, cy in cands:
            if cx < ox + ow and cx + w > ox and cy < oy + oh and cy + h > oy:
                continue  # overlaps
            # align the free axis to an edge when close
            if cx in (ox + ow, ox - w):
                for edge in (oy, oy + oh - h, oy + oh, oy - h):
                    if abs(cy - edge) <= threshold:
                        cy = edge
                        break
            else:
                for edge in (ox, ox + ow - w, ox + ow, ox - w):
                    if abs(cx - edge) <= threshold:
                        cx = edge
                        break
            dist = abs(cx - x) + abs(cy - y)
            if best is None or dist < best[0]:
                best = (dist, cx, cy)
    if best:
        return best[1], best[2]
    return x, y


def normalise_origin(positions):
    """KWin wants the top-left of the whole layout at 0,0. positions: {name: (x, y)} -> shifted copy."""
    if not positions:
        return {}
    mx = min(p[0] for p in positions.values())
    my = min(p[1] for p in positions.values())
    return {n: (x - mx, y - my) for n, (x, y) in positions.items()}


# ---------------------------------------------------------------- night light
NIGHT_FILE = 'kwinrc'
NIGHT_GROUP = 'NightColor'
NIGHT_MODES = ('Automatic', 'Times', 'Constant')


def _hhmm(text, default):
    m = re.match(r'^(\d{1,2}):(\d{2})', text or '')
    return f'{int(m.group(1)):02d}:{m.group(2)}' if m else default


def night_light():
    k = lambda key, d='': sysutil.kread(NIGHT_FILE, NIGHT_GROUP, key, d)  # noqa: E731
    live = sysutil.run(['busctl', '--user', 'get-property', 'org.kde.KWin', '/org/kde/KWin/NightLight', 'org.kde.KWin.NightLight', 'available'])
    cur = sysutil.run(['busctl', '--user', 'get-property', 'org.kde.KWin', '/org/kde/KWin/NightLight', 'org.kde.KWin.NightLight', 'currentTemperature'])
    mode = k('Mode', 'Automatic')
    return {'available': live.out.endswith('true') if live.code == 0 else None, 'active': k('Active', 'false') == 'true',
            'mode': mode if mode in NIGHT_MODES else 'Automatic', 'night_temp': int(k('NightTemperature', '4500') or 4500),
            'day_temp': int(k('DayTemperature', '6500') or 6500), 'evening': _hhmm(k('EveningBeginFixed'), '20:00'),
            'morning': _hhmm(k('MorningBeginFixed'), '06:00'), 'transition': int(k('TransitionTime', '30') or 30),
            'current_temp': int(cur.out.split()[-1]) if cur.code == 0 and cur.out.split()[-1].isdigit() else None}


def set_night_light(active=None, mode=None, night_temp=None, evening=None, morning=None, transition=None):
    def put(key, value):
        sysutil.kwrite(NIGHT_FILE, NIGHT_GROUP, key, value)
    if active is not None:
        put('Active', bool(active))
    if mode is not None:
        if mode not in NIGHT_MODES:
            raise ValueError('mode must be Automatic, Times or Constant')
        put('Mode', mode)
    if night_temp is not None:
        if not 1200 <= int(night_temp) <= 6500:
            raise ValueError('temperature must be between 1200 and 6500 K')
        put('NightTemperature', int(night_temp))
    for key, value in (('EveningBeginFixed', evening), ('MorningBeginFixed', morning)):
        if value is not None:
            if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value):
                raise ValueError('time must look like 20:30')
            put(key, value + ':00')
    if transition is not None:
        put('TransitionTime', max(1, min(120, int(transition))))
    sysutil.kwin_reconfigure()
    return night_light()


# A separate process owns preview rollback. Closing or crashing Settings closes
# its input pipe, so restoring the old mode does not depend on GTK staying alive.
def preview(changes,confirmation,events,timeout=15):
    import select
    import json
    import signal
    snapshot={out['name']:out for out in outputs()}
    rollback=[]
    for name,key,value in changes:
        if name not in snapshot or key not in ('mode','scale','rotation','position'):
            raise ValueError('Unsupported preview change.')
        old=snapshot[name]
        original=(old.get('mode') or {}).get('id') if key=='mode' else (f'{old["x"]},{old["y"]}' if key=='position' else old[key])
        if original is None:raise ValueError('The original display mode is unavailable.')
        rollback.append((name,key,original))
    accepted=False
    try:
        apply(changes)
        events.write('ready\n');events.flush()
        if select.select([confirmation],[],[],max(1,min(30,timeout)))[0]:
            accepted=confirmation.readline(32).strip()=='keep'
    finally:
        if not accepted:apply(rollback)
    events.write('kept\n' if accepted else 'reverted\n');events.flush()
    return accepted


if __name__=='__main__':
    import json
    import signal
    import sys
    def interrupted(signum,frame):raise InterruptedError('Display preview interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    if sys.argv[1:]!=['--preview']:sys.exit(64)
    try:
        raw=sys.stdin.readline(16385)
        if len(raw)>16384:raise ValueError('Display request is too large.')
        changes=json.loads(raw)
        if not isinstance(changes,list) or not 1<=len(changes)<=16:raise ValueError('Invalid display request.')
        preview(changes,sys.stdin,sys.stdout)
    except Exception:
        print('error',flush=True);sys.exit(1)
