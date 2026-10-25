# Adapted for MakkOS from Amerika OS (src/os/amerika/inputdev.py), GPL-3.0-only, Artemis Softworks LLC; MakkOS adaptations.
"""Input settings backend: keyboard layouts (kxkbrc, applied by KWin), key repeat (kcminputrc), pointing devices
(KWin's org.kde.KWin.InputDevice D-Bus, live, plus kcminputrc so the choice survives a restart)."""
import re
from pathlib import Path

from . import sysutil

XKB_LST = Path('/usr/share/X11/xkb/rules/evdev.lst')
NAME_OK = re.compile(r'^[A-Za-z0-9_.+\-]{1,40}$')
SWITCH_OPTIONS = [('', 'No shortcut'), ('grp:alt_shift_toggle', 'Alt + Shift'), ('grp:win_space_toggle', 'Super + Space'),
                  ('grp:ctrl_shift_toggle', 'Ctrl + Shift'), ('grp:alt_space_toggle', 'Alt + Space'), ('grp:caps_toggle', 'Caps Lock'),
                  ('grp:ctrl_alt_toggle', 'Ctrl + Alt')]
COMPOSE_OPTIONS = [('', 'Off'), ('compose:ralt', 'Right Alt'), ('compose:menu', 'Menu key'), ('compose:rctrl', 'Right Ctrl'),
                   ('compose:caps', 'Caps Lock'), ('compose:rwin', 'Right Super'), ('compose:prsc', 'Print Screen')]


# ---------------------------------------------------------------- keyboard layouts
def available_layouts():
    """[(code, name)] and {code: [(variant, name)]} from the system xkb database."""
    layouts, variants, section = [], {}, None
    try:
        text = XKB_LST.read_text(encoding='utf-8')
    except OSError:
        return [('us', 'English (US)')], {}
    for line in text.splitlines():
        if line.startswith('!'):
            section = line[1:].strip()
        elif section == 'layout' and line.strip():
            code, _, name = line.strip().partition(' ')
            layouts.append((code, name.strip()))
        elif section == 'variant' and line.strip():
            var, _, rest = line.strip().partition(' ')
            lay, _, name = rest.strip().partition(': ')
            variants.setdefault(lay.strip(), []).append((var, name.strip()))
    return sorted(layouts, key=lambda t: t[1]), variants


def layouts():
    """Configured layouts as [{'layout': 'us', 'variant': ''}]."""
    raw = sysutil.kread('kxkbrc', 'Layout', 'LayoutList', 'us')
    var = sysutil.kread('kxkbrc', 'Layout', 'VariantList', '')
    codes = [c for c in raw.split(',') if c] or ['us']
    variants = var.split(',') if var else []
    variants += [''] * (len(codes) - len(variants))
    return [{'layout': c, 'variant': variants[i]} for i, c in enumerate(codes)]


def _write_layouts(items):
    sysutil.kwrite('kxkbrc', 'Layout', 'Use', True)
    sysutil.kwrite('kxkbrc', 'Layout', 'LayoutList', ','.join(i['layout'] for i in items))
    sysutil.kwrite('kxkbrc', 'Layout', 'VariantList', ','.join(i['variant'] for i in items))
    sysutil.kwrite('kxkbrc', 'Layout', 'DisplayNames', ','.join('' for _ in items))
    sysutil.kwin_reconfigure()
    return layouts()


def add_layout(code, variant=''):
    if not NAME_OK.match(code) or (variant and not NAME_OK.match(variant)):
        raise ValueError('invalid layout')
    cur = layouts()
    if any(i['layout'] == code and i['variant'] == variant for i in cur):
        return cur
    if len(cur) >= 4:
        raise ValueError('KDE supports at most four keyboard layouts.')
    return _write_layouts(cur + [{'layout': code, 'variant': variant}])


def remove_layout(index):
    cur = layouts()
    if len(cur) <= 1:
        raise ValueError('At least one keyboard layout is needed.')
    if not 0 <= index < len(cur):
        raise ValueError('no such layout')
    return _write_layouts(cur[:index] + cur[index + 1:])


def move_layout(index, delta):
    cur = layouts()
    j = index + delta
    if not (0 <= index < len(cur) and 0 <= j < len(cur)):
        return cur
    cur[index], cur[j] = cur[j], cur[index]
    return _write_layouts(cur)


def switch_layout(index=None):
    """Switch the active layout now (None = next)."""
    if index is None:
        return sysutil.run(['busctl', '--user', 'call', 'org.kde.keyboard', '/Layouts', 'org.kde.KeyboardLayouts', 'switchToNextLayout']).code == 0
    return sysutil.run(['busctl', '--user', 'call', 'org.kde.keyboard', '/Layouts', 'org.kde.KeyboardLayouts', 'setLayout', 'u', str(int(index))]).code == 0


def active_layout():
    res = sysutil.run(['busctl', '--user', 'call', 'org.kde.keyboard', '/Layouts', 'org.kde.KeyboardLayouts', 'getLayout'])
    return int(res.out.split()[-1]) if res.code == 0 and res.out.split() and res.out.split()[-1].isdigit() else 0


def xkb_options():
    raw = sysutil.kread('kxkbrc', 'Layout', 'Options', '')
    return [o for o in raw.split(',') if o]


def _set_option_group(prefix, value):
    opts = [o for o in xkb_options() if not o.startswith(prefix)]
    if value:
        if not value.startswith(prefix) or not NAME_OK.match(value.replace(':', '_')):
            raise ValueError('invalid option')
        opts.append(value)
    sysutil.kwrite('kxkbrc', 'Layout', 'ResetOldOptions', True)
    sysutil.kwrite('kxkbrc', 'Layout', 'Options', ','.join(opts))
    sysutil.kwin_reconfigure()
    return opts


def switch_shortcut():
    return next((o for o in xkb_options() if o.startswith('grp:')), '')


def set_switch_shortcut(option):
    if option not in dict(SWITCH_OPTIONS):
        raise ValueError('unknown layout switch shortcut')
    return _set_option_group('grp:', option)


def compose_key():
    return next((o for o in xkb_options() if o.startswith('compose:')), '')


def set_compose_key(option):
    if option not in dict(COMPOSE_OPTIONS):
        raise ValueError('unknown compose key')
    return _set_option_group('compose:', option)


# ---------------------------------------------------------------- key repeat
def repeat():
    return {'delay': int(sysutil.kread('kcminputrc', 'Keyboard', 'RepeatDelay', '600') or 600),
            'rate': int(float(sysutil.kread('kcminputrc', 'Keyboard', 'RepeatRate', '25') or 25))}


def set_repeat(delay=None, rate=None):
    if delay is not None:
        sysutil.kwrite('kcminputrc', 'Keyboard', 'RepeatDelay', max(150, min(2000, int(delay))))
    if rate is not None:
        sysutil.kwrite('kcminputrc', 'Keyboard', 'RepeatRate', max(2, min(100, int(rate))))
    sysutil.kwin_reconfigure()
    return repeat()


# ---------------------------------------------------------------- modifier keys (xkb options in kxkbrc, applied by KWin)
MODIFIER_REMAPS = [('', 'Default'), ('caps:ctrl_modifier', 'Caps Lock acts as Control'), ('caps:escape', 'Caps Lock acts as Escape'),
                   ('caps:super', 'Caps Lock acts as Super'), ('caps:none', 'Caps Lock disabled'),
                   ('ctrl:swap_lalt_lctl', 'Swap left Control and left Alt'), ('altwin:swap_lalt_lwin', 'Swap left Alt and left Super')]
_REMAP_PREFIXES = ('caps:', 'ctrl:', 'altwin:')


def modifier_remap():
    return next((o for o in xkb_options() if o.startswith(_REMAP_PREFIXES)), '')


def set_modifier_remap(option):
    if option not in dict(MODIFIER_REMAPS):
        raise ValueError('unknown modifier remap')
    opts = [o for o in xkb_options() if not o.startswith(_REMAP_PREFIXES)]
    if option:
        opts.append(option)
    sysutil.kwrite('kxkbrc', 'Layout', 'ResetOldOptions', True)
    sysutil.kwrite('kxkbrc', 'Layout', 'Options', ','.join(opts))
    sysutil.kwin_reconfigure()
    return opts


# ---------------------------------------------------------------- pointing devices (KWin InputDevice D-Bus)
KWIN = 'org.kde.KWin'
DEV_IFACE = 'org.kde.KWin.InputDevice'
DEV_PATH = '/org/kde/KWin/InputDevice/'
# (property, dbus signature, kind). kind: bool / float
POINTER_PROPS = {'tapToClick': 'b', 'tapAndDrag': 'b', 'tapDragLock': 'b', 'naturalScroll': 'b', 'pointerAcceleration': 'd', 'leftHanded': 'b',
                 'scrollFactor': 'd', 'disableWhileTyping': 'b', 'middleEmulation': 'b', 'scrollTwoFinger': 'b', 'scrollEdge': 'b',
                 'clickMethodAreas': 'b', 'clickMethodClickfinger': 'b', 'pointerAccelerationProfileFlat': 'b',
                 'pointerAccelerationProfileAdaptive': 'b', 'enabled': 'b', 'disableEventsOnExternalMouse': 'b'}


def _prop(sysname, prop):
    res = sysutil.run(['busctl', '--user', 'get-property', KWIN, DEV_PATH + sysname, DEV_IFACE, prop], timeout=4)
    if res.code != 0 or ' ' not in res.out:
        return None
    sig, _, val = res.out.partition(' ')
    if sig == 'b':
        return val == 'true'
    if sig in ('d', 'u', 'i'):
        try:
            return float(val) if sig == 'd' else int(val)
        except ValueError:
            return None
    if sig == 's':
        return val.strip('"')
    return val


def pointing_devices():
    """Touchpads, mice and tablets known to KWin, with the properties each supports."""
    res = sysutil.run(['busctl', '--user', 'get-property', KWIN, '/org/kde/KWin/InputDevice', 'org.kde.KWin.InputDeviceManager', 'devicesSysNames'])
    names = re.findall(r'"(event\d+)"', res.out)
    out = []
    for n in names:
        if _prop(n, 'pointer') is not True and _prop(n, 'tabletTool') is not True and _prop(n, 'touchpad') is not True:
            continue
        kind = 'touchpad' if _prop(n, 'touchpad') else ('tablet' if _prop(n, 'tabletTool') else 'mouse')
        dev = {'sysname': n, 'name': _prop(n, 'name') or n, 'kind': kind, 'vendor': _prop(n, 'vendor'), 'product': _prop(n, 'product'),
               'props': {}, 'supported': {}}
        for prop in POINTER_PROPS:
            value = _prop(n, prop)
            if value is not None:
                dev['props'][prop] = value
        for prop in ('NaturalScroll', 'PointerAcceleration', 'LeftHanded', 'MiddleEmulation', 'ScrollTwoFinger', 'DisableWhileTyping',
                     'PointerAccelerationProfileFlat'):
            dev['supported'][prop[0].lower() + prop[1:]] = _prop(n, 'supports' + prop)
        dev['supported']['tapToClick'] = kind == 'touchpad'
        dev['supported']['scrollFactor'] = True
        out.append(dev)
    return out


def set_device(dev, prop, value):
    """Apply live through KWin and persist in kcminputrc ([Libinput][vendor][product][name])."""
    if prop not in POINTER_PROPS:
        raise ValueError(f'unknown input property {prop}')
    if not re.fullmatch(r'event\d{1,3}', dev['sysname']):
        raise ValueError('invalid device')
    sig = POINTER_PROPS[prop]
    if sig == 'd':
        value = float(value)
        if prop == 'pointerAcceleration':
            value = max(-1.0, min(1.0, value))
        if prop == 'scrollFactor':
            value = max(0.1, min(10.0, value))
        text = repr(value)
    else:
        text = 'true' if value else 'false'
    ok = sysutil.run(['busctl', '--user', 'set-property', KWIN, DEV_PATH + dev['sysname'], DEV_IFACE, prop, sig, text]).code == 0
    if dev.get('vendor') is not None and dev.get('product') is not None:
        group = f"Libinput][{dev['vendor']}][{dev['product']}][{dev['name']}"
        key = prop[0].upper() + prop[1:]
        sysutil.kwrite('kcminputrc', group, key, text)
    return ok
