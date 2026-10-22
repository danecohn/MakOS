"""Launcher Bar: size, magnification, position, autohide, recents. Saved to settings.json, which the shell re-reads live."""
from ..backends import look
from . import widgets as W


def build(col, ctx):
    d = ctx.data
    s = W.section(col, 'Size')
    W.scale_row(s, 'Icon size', 32, 96, 1, d['launcher_size'], lambda v: ctx.do(look.put, launcher_size=round(v), ok='Icon size changed.'),
                fmt=lambda v: f'{int(v)} px')
    W.switch_row(s, 'Magnification', d['launcher_magnify'], lambda v: ctx.do(look.put, launcher_magnify=v, ok='Saved.'),
                 hint='Icons grow as the pointer moves over them. Off when Reduce motion is on.')
    W.scale_row(s, 'Magnification amount', 0, 100, 5, d['launcher_magnify_percent'],
                lambda v: ctx.do(look.put, launcher_magnify_percent=round(v), ok='Saved.'), fmt=lambda v: f'{int(v)} %')
    s = W.section(col, 'Position')
    W.choice_row(s, 'Position on screen', [('bottom', 'Bottom'), ('left', 'Left'), ('right', 'Right')], d['launcher_position'],
                 lambda v: ctx.do(look.put, launcher_position=v, ok='Launcher bar moved.'))
    W.switch_row(s, 'Automatically hide and show the launcher bar', d['launcher_autohide'],
                 lambda v: ctx.do(look.put, launcher_autohide=v, ok=ctx.saved('launcher_autohide')),
                 hint='Some autohide cases are still being completed in this development build.')
    s = W.section(col, 'Recent applications')
    W.switch_row(s, 'Show recent applications', d['launcher_recents'], lambda v: ctx.do(look.put, launcher_recents=v, ok=ctx.saved('launcher_recents')),
                 hint='Not implemented in the launcher bar yet: the choice is stored, but the bar does not show recents.', sensitive=False)
