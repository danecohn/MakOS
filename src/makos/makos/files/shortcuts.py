"""Keyboard shortcut table. Ctrl combos and Super combos mirror each other for the classic conventions."""
from gi.repository import Gdk

CTRL, SUPER = Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SUPER_MASK
SHIFT, ALT = Gdk.ModifierType.SHIFT_MASK, Gdk.ModifierType.ALT_MASK
RELEVANT = CTRL | SUPER | SHIFT | ALT

# (keyval, shift, alt) -> action when the "primary" modifier (Ctrl or Super) is held.
PRIMARY = {
    (Gdk.KEY_c, False, False): 'copy', (Gdk.KEY_x, False, False): 'cut', (Gdk.KEY_v, False, False): 'paste',
    (Gdk.KEY_a, False, False): 'select-all', (Gdk.KEY_z, False, False): 'undo', (Gdk.KEY_z, True, False): 'redo',
    (Gdk.KEY_y, False, False): 'redo',
    (Gdk.KEY_BackSpace, False, False): 'trash', (Gdk.KEY_Delete, False, False): 'trash',
    (Gdk.KEY_Down, False, False): 'open', (Gdk.KEY_o, False, False): 'open', (Gdk.KEY_Up, False, False): 'parent',
    (Gdk.KEY_i, False, False): 'info', (Gdk.KEY_d, False, False): 'duplicate',
    (Gdk.KEY_n, True, False): 'new-folder', (Gdk.KEY_n, False, False): 'new-window',
    (Gdk.KEY_t, False, False): 'new-tab', (Gdk.KEY_w, False, False): 'close-tab',
    (Gdk.KEY_f, False, False): 'search', (Gdk.KEY_l, False, False): 'location',
    (Gdk.KEY_k, False, False): 'connect', (Gdk.KEY_r, False, False): 'reload',
    (Gdk.KEY_1, False, False): 'view-icons', (Gdk.KEY_2, False, False): 'view-list',
    (Gdk.KEY_3, False, False): 'view-columns', (Gdk.KEY_4, False, False): 'view-cover',
    (Gdk.KEY_bracketleft, False, False): 'back', (Gdk.KEY_bracketright, False, False): 'forward',
    (Gdk.KEY_period, True, False): 'toggle-hidden', (Gdk.KEY_h, True, False): 'toggle-hidden',
    (Gdk.KEY_Delete, True, False): 'empty-trash', (Gdk.KEY_BackSpace, True, False): 'empty-trash',
    (Gdk.KEY_e, False, False): 'extract', (Gdk.KEY_e, True, False): 'compress',
    (Gdk.KEY_y, True, False): 'quicklook', (Gdk.KEY_plus, False, False): 'zoom-in', (Gdk.KEY_equal, False, False): 'zoom-in',
    (Gdk.KEY_minus, False, False): 'zoom-out', (Gdk.KEY_Tab, False, False): 'next-tab',
}
PLAIN = {
    (Gdk.KEY_space, False, False): 'quicklook', (Gdk.KEY_Escape, False, False): 'escape',
    (Gdk.KEY_F2, False, False): 'rename', (Gdk.KEY_F5, False, False): 'reload',
    (Gdk.KEY_Delete, False, False): 'trash', (Gdk.KEY_Delete, True, False): 'delete',
    (Gdk.KEY_Return, False, False): 'open', (Gdk.KEY_KP_Enter, False, False): 'open',
    (Gdk.KEY_Left, False, True): 'back', (Gdk.KEY_Right, False, True): 'forward',
    (Gdk.KEY_Up, False, True): 'parent', (Gdk.KEY_Down, False, True): 'open',
    (Gdk.KEY_BackSpace, False, False): 'parent',
}


def resolve(keyval, state):
    """Return an action name for a key press or None. ``state`` is a Gdk.ModifierType."""
    state = state & RELEVANT
    lower = Gdk.keyval_to_lower(keyval)
    shift, alt = bool(state & SHIFT), bool(state & ALT)
    primary = bool(state & (CTRL | SUPER))
    if primary and (state & (CTRL | SUPER)) == (CTRL | SUPER):
        return None
    if primary:
        if alt:
            return None
        return PRIMARY.get((lower, shift, False))
    return PLAIN.get((lower, shift, alt))
