"""Keyboard: repeat rate and delay, modifier remapping, compose key and the shortcut editor."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from ..backends import inputdev
from . import shortcuts_ui, widgets as W


def build(col, ctx):
    s = W.section(col, 'Key repeat')
    rep = inputdev.repeat()
    W.scale_row(s, 'Delay until repeat', 150, 2000, 50, rep['delay'], lambda v: ctx.do(inputdev.set_repeat, delay=round(v), ok='Repeat delay changed.'),
                fmt=lambda v: f'{int(v)} ms', hint='Shorter is faster.')
    W.scale_row(s, 'Key repeat rate', 2, 100, 1, rep['rate'], lambda v: ctx.do(inputdev.set_repeat, rate=round(v), ok='Repeat rate changed.'),
                fmt=lambda v: f'{int(v)} / s')
    test = Gtk.Entry(placeholder_text='Hold a key here to try the repeat rate', hexpand=True)
    s.append(test)

    s = W.section(col, 'Modifier keys')
    W.choice_row(s, 'Remap', inputdev.MODIFIER_REMAPS, inputdev.modifier_remap(), lambda v: ctx.do(inputdev.set_modifier_remap, v, ok='Modifier keys changed.'),
                 hint='Applies to every application in the session.')
    W.choice_row(s, 'Compose key', inputdev.COMPOSE_OPTIONS, inputdev.compose_key(), lambda v: ctx.do(inputdev.set_compose_key, v, ok='Compose key changed.'))

    s = W.section(col, 'Shortcuts')
    W.note(s, 'Choose Change, then press the new combination. Conflicts with other shortcuts are shown before anything changes.')
    shortcuts_ui.build(s, ctx)
