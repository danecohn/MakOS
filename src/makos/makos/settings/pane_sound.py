"""Sound: output and input devices, volume, balance, mute, per-application streams (PipeWire via pactl)."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import audio
from . import widgets as W


def build(col, ctx):
    holder = ui.box(True, 14)
    col.append(holder)

    def load():
        return {'out': audio.devices('output'), 'in': audio.devices('input'), 'apps': audio.apps()}

    def reload(_r=None):
        ui.clear(holder)
        W.loading(holder, load, render)

    def device_block(box, kind, devs):
        s = W.section(box, 'Output' if kind == 'output' else 'Input')
        if not devs:
            W.unavailable(s, 'No %s devices were found.' % ('output' if kind == 'output' else 'input'))
            return
        choices = [(d['name'], d['description'] + ('' if d['default'] else '')) for d in devs]
        current = next((d for d in devs if d['default']), devs[0])
        W.choice_row(s, 'Use', choices, current['name'], lambda v: ctx.do(audio.set_default, kind, v, ok='Default device changed.', done=reload))
        W.scale_row(s, 'Volume', 0, 150, 1, current['volume'], lambda v: ctx.do(audio.set_volume, kind, current['name'], round(v), ok='Volume changed.'),
                    fmt=lambda v: f'{int(v)} %')
        W.switch_row(s, 'Mute', current['muted'], lambda v: ctx.do(audio.set_mute, kind, current['name'], v, ok='Saved.'))
        if kind == 'output' and current['channels'] >= 2:
            W.scale_row(s, 'Balance', -1.0, 1.0, 0.1, current['balance'], lambda v: ctx.do(audio.set_balance, current['name'], v, current['channels'], ok='Balance changed.'),
                        fmt=lambda v: 'Centre' if abs(v) < .05 else (f'Left {int(-v * 100)} %' if v < 0 else f'Right {int(v * 100)} %'))
        if len(current['ports']) > 1:
            W.choice_row(s, 'Port', [(p['name'], p['description'] + ('' if p['available'] else ' (unplugged)')) for p in current['ports']],
                         current['active_port'], lambda v: ctx.do(audio.set_port, kind, current['name'], v, ok='Port changed.'))
        if kind == 'output':
            W.button_row(s, 'Test', 'Play a Test Tone', lambda: ctx.do(audio.test_tone, current['name'], ok='Playing a short tone.'))

    def render(box, info):
        device_block(box, 'output', info['out'])
        device_block(box, 'input', info['in'])
        s = W.section(box, 'Applications playing sound')
        if not info['apps']:
            W.note(s, 'No application is playing sound right now.')
        for app in info['apps']:
            W.scale_row(s, app['name'], 0, 150, 1, app['volume'], lambda v, app=app: ctx.do(audio.set_app_volume, app['index'], round(v), ok='Volume changed.'),
                        fmt=lambda v: f'{int(v)} %')
        W.button_row(s, '', 'Refresh', reload)
    reload()
