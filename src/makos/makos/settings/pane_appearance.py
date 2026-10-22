"""Appearance: accent / Graphite variant, window backgrounds, text size, scroll bars, transparency, motion."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import look
from . import model, widgets as W

ACCENT_LABELS = {'blue': 'Blue', 'graphite': 'Graphite', 'teal': 'Teal', 'green': 'Green', 'orange': 'Orange', 'red': 'Red', 'purple': 'Purple'}


def build(col, ctx):
    d = ctx.data
    s = W.section(col, 'Colour')
    W.choice_row(s, 'Accent colour', [(a, ACCENT_LABELS[a]) for a in model.ACCENTS], d['accent'],
                 lambda v: ctx.do(look.set_accent, v, ok='Accent changed.'),
                 hint='Graphite makes the controls neutral grey. Applies to MakkOS windows immediately.')
    W.switch_row(s, 'Use pinstripe window backgrounds', d['pinstripes'], lambda v: ctx.do(look.set_pinstripes, v, ok='Saved.'))
    s = W.section(col, 'Text and scrolling')
    W.scale_row(s, 'Font size', 10, 18, 1, d['font_size'], lambda v: ctx.do(look.set_font_size, round(v), ok='Font size changed.'),
                fmt=lambda v: f'{int(v)} px', hint='Base size for MakkOS windows (default 12).')
    W.choice_row(s, 'Show scroll bars', [('auto', 'Automatically'), ('always', 'Always')], d['scrollbars'],
                 lambda v: ctx.do(look.set_scrollbars, v, ok='Scroll bar behaviour changed.'),
                 hint='Other GTK applications follow after they are restarted.')
    s = W.section(col, 'Transparency and motion')
    W.switch_row(s, 'Reduce transparency', d['reduce_transparency'], lambda v: ctx.do(look.set_reduce_transparency, v, ok='Saved.'),
                 hint='Menu bar, launcher bar, Seek and Spread become opaque.')
    W.switch_row(s, 'Reduce motion', d['reduce_motion'], lambda v: ctx.do(look.set_reduce_motion, v, ok='Motion setting changed.'),
                 hint='Turns off MakkOS animations and speeds KWin effects up to instant.')
    s = W.section(col, 'Preview')
    card = ui.box(True, 8, 'hint-card')
    row = ui.box(spacing=12)
    row.append(ui.button('Cancel', lambda: None))
    row.append(ui.button('Default button', lambda: None, 'suggested-action'))
    card.append(row)
    card.append(Gtk.Entry(placeholder_text='Inset text field'))
    card.append(Gtk.Label(label='Glass & Metal • DejaVu Sans, an open font supplied by Ubuntu', xalign=0, css_classes=['subtitle']))
    s.append(card)
