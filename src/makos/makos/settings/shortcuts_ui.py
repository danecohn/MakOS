"""Shortcut editor widget (shared by Keyboard and Desks & Spread) and the Gdk key -> sequence conversion."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, Gtk

from .. import ui
from ..backends import shortcuts
from . import widgets as W

MOD_ORDER = (('Meta', Gdk.ModifierType.SUPER_MASK), ('Ctrl', Gdk.ModifierType.CONTROL_MASK),
             ('Alt', Gdk.ModifierType.ALT_MASK), ('Shift', Gdk.ModifierType.SHIFT_MASK))
_MODIFIER_KEYS = {Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
                  Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift}


def sequence_from_event(keyval, state):
    """'Meta+Space' style text for a key press, or None while only modifiers are held."""
    if keyval in _MODIFIER_KEYS:
        return None
    mods = [name for name, mask in MOD_ORDER if state & mask]
    keyval = Gdk.keyval_to_lower(keyval)
    uni = Gdk.keyval_to_unicode(keyval)
    if keyval == Gdk.KEY_space:
        key = 'Space'
    elif keyval == Gdk.KEY_ISO_Left_Tab:
        key = 'Tab'
    elif uni and chr(uni).isprintable() and chr(uni) != ' ':
        key = chr(uni).upper()
    else:
        key = Gdk.keyval_name(keyval) or ''
    if not key:
        return None
    return shortcuts.normalise('+'.join(mods + [key]))


def record(ctx, title, on_sequence):
    """Small window that waits for the next key combination. Escape cancels."""
    w = ui.window(ctx.app, 'Shortcut', 380, 170)
    col = ui.box(True, 12, 'sheet')
    col.append(Gtk.Label(label=f'Press the new shortcut for “{title}”', wrap=True, xalign=0))
    hint = Gtk.Label(label='Escape cancels.', xalign=0, css_classes=['subtitle'])
    col.append(hint)
    w.set_child(col)
    keys = Gtk.EventControllerKey()

    def pressed(_c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            w.close()
            return True
        seq = sequence_from_event(keyval, state)
        if seq:
            w.close()
            on_sequence(seq)
        return True
    keys.connect('key-pressed', pressed)
    w.add_controller(keys)
    w.present()


def build(parent, ctx, only=None):
    """List shortcuts (only: optional predicate on the shortcut title). Conflicts are reported before anything changes."""
    entries = [e for e in shortcuts.listing() if not only or only(e['title'])]
    if not entries:
        W.unavailable(parent, 'No shortcuts were found (the compositor bridge file is missing).')
        return
    for e in entries:
        line = ui.box(spacing=10)
        name = Gtk.Label(label=e['title'], xalign=0, hexpand=True)
        keys = Gtk.Label(label=e['current'] or 'none', css_classes=['subtitle'], width_chars=16, xalign=1)
        line.append(name)
        line.append(keys)

        def change(seq, e=e, keys=keys, allow=False):
            try:
                final = shortcuts.set_shortcut(e['id'], seq, allow_conflict=allow)
            except ValueError as error:
                msg = str(error)
                if 'already used' in msg:
                    W.dialog(ctx.app, 'Shortcut conflict', msg + ' Use it anyway? The other action keeps its own binding too.',
                             [('Cancel', None, None), ('Use Anyway', lambda: change(seq, e, keys, True), 'suggested-action')])
                else:
                    ctx.flash(msg, True)
                return
            except RuntimeError as error:
                ctx.flash(str(error), True)
                return
            keys.set_text(final or 'none')
            ctx.flash('Shortcut changed.')
        line.append(ui.button('Change…', lambda e=e, change=change: record(ctx, e['title'], change)))
        line.append(ui.button('Reset', lambda e=e, keys=keys: _reset(ctx, e, keys)))
        warn = '' if not e['conflicts'] else 'Also used by: ' + ', '.join(c['action'] for c in e['conflicts'][:2])
        parent.append(line)
        if warn:
            parent.append(Gtk.Label(label=warn, xalign=0, css_classes=['settings-status', 'error']))


def _reset(ctx, e, keys):
    try:
        keys.set_text(shortcuts.reset(e['id']) or 'none')
        ctx.flash('Shortcut restored.')
    except (ValueError, RuntimeError) as error:
        ctx.flash(str(error), True)
