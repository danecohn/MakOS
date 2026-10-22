"""Accessibility: large text, contrast, motion, keyboard aids, screen reader, zoom."""
from ..backends import accessibility as acc
from . import widgets as W


def build(col, ctx):
    st = acc.state()
    s = W.section(col, 'Seeing')
    W.choice_row(s, 'Text size', [(v, t) for v, t in acc.TEXT_SCALES] if st['text_scale'] in dict(acc.TEXT_SCALES)
                 else [(st['text_scale'], f"{st['text_scale']:g}×")] + list(acc.TEXT_SCALES), st['text_scale'],
                 lambda v: ctx.do(acc.set_text_scale, v, ok='Text size changed.'))
    W.switch_row(s, 'Increase contrast', st['high_contrast'], lambda v: ctx.do(acc.set_high_contrast, v, ok='Contrast changed.'))
    W.switch_row(s, 'Reduce transparency', st['reduce_transparency'], lambda v: ctx.do(acc.set_reduce_transparency, v, ok='Saved.'))
    W.switch_row(s, 'Reduce motion', st['reduce_motion'], lambda v: ctx.do(acc.set_reduce_motion, v, ok='Saved.'))
    W.switch_row(s, 'Zoom the screen', st['zoom'], lambda v: ctx.do(acc.set_zoom, v, ok='Zoom changed.'), hint='Uses the compositor zoom effect.')
    W.scale_row(s, 'Zoom level', 1.0, 8.0, 0.5, st['zoom_level'], lambda v: ctx.do(acc.set_zoom, st['zoom'], v, ok='Zoom level saved.'), fmt=lambda v: f'{v:g}×')
    s = W.section(col, 'Hearing and speech')
    if st['orca_installed']:
        W.switch_row(s, 'Screen reader (Orca)', st['screen_reader'], lambda v: ctx.do(acc.set_screen_reader, v, ok='Screen reader changed.'))
    else:
        W.unavailable(s, 'The Orca screen reader is not installed. Install it with: sudo apt install orca')
    s = W.section(col, 'Keyboard')
    W.switch_row(s, 'Sticky keys', st['sticky_keys'], lambda v: ctx.do(acc.set_keys, sticky=v, ok='Saved.'), hint='Press modifier keys one at a time.')
    W.switch_row(s, 'Slow keys', st['slow_keys'], lambda v: ctx.do(acc.set_keys, slow=v, ok='Saved.'))
    W.scale_row(s, 'Slow keys delay', 50, 2000, 50, st['slow_keys_delay'], lambda v: ctx.do(acc.set_keys, slow_delay=round(v), ok='Saved.'), fmt=lambda v: f'{int(v)} ms')
    W.switch_row(s, 'Bounce keys', st['bounce_keys'], lambda v: ctx.do(acc.set_keys, bounce=v, ok='Saved.'))
    W.note(s, 'Keyboard aids are saved for the compositor; they take effect in sessions that run its keyboard accessibility service.')
