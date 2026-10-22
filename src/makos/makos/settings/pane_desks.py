"""Desks & Spread: number of desks, hot corners and the MakkOS window-management shortcuts."""
from ..backends import desks
from . import shortcuts_ui, widgets as W


def build(col, ctx):
    s = W.section(col, 'Desks')
    n = desks.count()
    W.scale_row(s, 'Number of desks', desks.MIN_DESKS, desks.MAX_DESKS, 1, n,
                lambda v: ctx.do(desks.set_count, round(v), ok=lambda r: f"{r['count']} desks." + ('' if r['live'] else ' Applies when the compositor next reloads.')),
                fmt=lambda v: str(int(v)))
    s = W.section(col, 'Hot corners')
    W.note(s, 'Move the pointer into a screen corner to run an action. Applied through the compositor bridge script.')
    current = desks.hot_corners()
    for corner, label in desks.CORNER_LABELS:
        W.choice_row(s, label, desks.CORNER_ACTIONS, current.get(corner, 'none'),
                     lambda v, c=corner: ctx.do(desks.set_hot_corner, c, v, ok='Hot corner changed.'))
    s = W.section(col, 'Shortcuts')
    W.note(s, 'Window and desk shortcuts. A shortcut that another action already uses is reported before it changes.')
    shortcuts_ui.build(s, ctx, only=lambda t: t in {'Spread', 'Desks', 'Seek', 'Application switcher', 'Show desktop', 'Next application window'})
