"""Displays: resolution, refresh, scale (including fractional), rotation, arrangement and Night Shift via kscreen-doctor / KWin.

Resolution, scale, rotation and position changes are previewed by a separate process that reverts them after 15 seconds
unless you press Keep, so a bad mode can never strand you (that process survives a crash of Settings).
"""
import gi

gi.require_version('Gtk', '4.0')
import json
import os
import subprocess
import sys

from gi.repository import GLib, Gtk

from .. import common, ui
from ..backends import displays
from . import widgets as W

PREVIEWABLE = ('mode', 'scale', 'rotation', 'position')


class Preview:
    """Runs `python -m makos.backends.displays --preview` and talks to it over pipes."""

    def __init__(self, ctx, changes, on_end):
        self.ctx, self.on_end = ctx, on_end
        env = dict(os.environ)
        env.pop('LD_PRELOAD', None)
        env['PYTHONPATH'] = os.pathsep.join([str(common.SOURCE)] + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
        try:
            self.proc = subprocess.Popen([sys.executable, '-m', 'makos.backends.displays', '--preview'],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
            self.proc.stdin.write(json.dumps(changes) + '\n')
            self.proc.stdin.flush()
        except OSError as error:
            ctx.flash('Could not start the display preview: ' + str(error), True)
            on_end(False)
            return
        W.run_async(self._wait_ready, self._ready, lambda e: (ctx.flash('Display change failed.', True), on_end(False)))

    def _wait_ready(self):
        return self.proc.stdout.readline().strip()

    def _ready(self, line):
        if line != 'ready':
            self.ctx.flash('The display did not accept that setting.', True)
            self.proc.wait()
            self.on_end(False)
            return
        self.left = 15
        self.label = Gtk.Label(label='', wrap=True, xalign=0)
        self.win = W.dialog(self.ctx.app, 'Keep these display settings?', 'Keep the new display settings?', [
            ('Revert', self.revert, None), ('Keep', self.keep, 'suggested-action')])
        self.win.get_child().insert_child_after(self.label, self.win.get_child().get_first_child())
        self.timer = GLib.timeout_add_seconds(1, self._tick)
        self._tick(first=True)
        W.run_async(self._wait_end, self._ended, lambda e: self.on_end(False))

    def _tick(self, first=False):
        if not first:
            self.left -= 1
        self.label.set_text(f'The previous settings return in {max(self.left, 0)} seconds.')
        return self.left > 0

    def _wait_end(self):
        return self.proc.stdout.readline().strip()

    def _ended(self, line):
        self.proc.wait()
        if getattr(self, 'win', None):
            self.win.close()
        self.ctx.flash('Display settings kept.' if line == 'kept' else 'Previous display settings restored.')
        self.on_end(line == 'kept')

    def keep(self):
        try:
            self.proc.stdin.write('keep\n')
            self.proc.stdin.flush()
        except OSError:
            pass

    def revert(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass


def build(col, ctx):
    state = {'busy': False}
    holder = ui.box(True, 14)
    col.append(holder)

    def reload():
        ui.clear(holder)
        W.loading(holder, displays.outputs, render)

    def change(changes):
        if state['busy']:
            return
        state['busy'] = True

        def finished(_kept):
            state['busy'] = False
            reload()
        if all(c[1] in PREVIEWABLE for c in changes):
            Preview(ctx, changes, finished)
        else:
            ctx.do(displays.apply, changes, ok='Display setting changed.', done=lambda _r: finished(True))

    def render(box, outs):
        if not outs:
            W.unavailable(box, 'No displays were reported. This needs kscreen-doctor and a running KWin session.')
        for out in outs:
            s = W.section(box, out['name'] + (' (main display)' if out['primary'] else ''))
            res = displays.resolutions(out)
            cur = (out['width'], out['height'])
            if res:
                W.choice_row(s, 'Resolution', [(r, f'{r[0]} × {r[1]}') for r, _m in res], cur if cur in dict(res) else res[0][0],
                             lambda r, out=out: change([(out['name'], 'mode', displays.mode_for(out, r[0], r[1])['id'])]))
                rates = displays.refresh_rates(out, *cur)
                if len(rates) > 1:
                    W.choice_row(s, 'Refresh rate', [(r, f'{r:g} Hz') for r in rates], (out['mode'] or {}).get('refresh', rates[0]),
                                 lambda r, out=out, cur=cur: change([(out['name'], 'mode', displays.mode_for(out, cur[0], cur[1], r)['id'])]))
            scales = sorted(set(displays.SCALES + [out['scale']]))
            W.choice_row(s, 'Scale', [(v, f'{round(v * 100)} %') for v in scales], out['scale'],
                         lambda v, out=out: change([(out['name'], 'scale', v)]), hint='Fractional scales such as 125 % and 150 % are supported.')
            W.choice_row(s, 'Rotation', [('normal', 'Standard'), ('left', '90° left'), ('inverted', '180°'), ('right', '90° right')], out['rotation'],
                         lambda v, out=out: change([(out['name'], 'rotation', v)]))
            if not out['primary'] and len(outs) > 1:
                W.button_row(s, 'Main display', 'Use as Main Display', lambda out=out: ctx.do(displays.apply, [(out['name'], 'primary', True)],
                                                                                              ok='Main display changed.', done=lambda _r: reload()))
        if len(outs) > 1:
            arrangement(box, outs)
        night(box)

    def arrangement(box, outs):
        s = W.section(box, 'Arrangement')
        W.note(s, 'Drag the displays to arrange them. Screens snap to each other so they touch.')
        area = Gtk.DrawingArea(content_width=420, content_height=170)
        rects = {o['name']: dict(o) for o in outs}
        total_w = max(o['x'] + o['logical'][0] for o in outs) + 400
        total_h = max(o['y'] + o['logical'][1] for o in outs) + 400
        scale = min(420 / total_w, 170 / total_h)
        drag = {'name': None}

        def draw(_a, cr, w, h):
            for name, o in rects.items():
                x, y, rw, rh = o['x'] * scale + 10, o['y'] * scale + 10, o['logical'][0] * scale, o['logical'][1] * scale
                cr.set_source_rgb(.56, .74, .93) if o['primary'] else cr.set_source_rgb(.78, .82, .87)
                cr.rectangle(x, y, rw, rh)
                cr.fill_preserve()
                cr.set_source_rgb(.25, .35, .5)
                cr.stroke()
                cr.move_to(x + 6, y + 16)
                cr.show_text(name)
        area.set_draw_func(draw)
        gesture = Gtk.GestureDrag()

        def begin(_g, x, y):
            drag['name'] = None
            for name, o in rects.items():
                rx, ry = o['x'] * scale + 10, o['y'] * scale + 10
                if rx <= x <= rx + o['logical'][0] * scale and ry <= y <= ry + o['logical'][1] * scale:
                    drag.update(name=name, ox=o['x'], oy=o['y'])

        def move(_g, dx, dy):
            if drag['name']:
                o = rects[drag['name']]
                o['x'], o['y'] = round(drag['ox'] + dx / scale), round(drag['oy'] + dy / scale)
                area.queue_draw()

        def end(_g, dx, dy):
            name = drag['name']
            if not name:
                return
            move(_g, dx, dy)
            others = [r for n, r in rects.items() if n != name]
            snapped = displays.snap(rects[name], others)
            rects[name]['x'], rects[name]['y'] = snapped
            norm = displays.normalise_origin({n: (r['x'], r['y']) for n, r in rects.items()})
            changes = [(n, 'position', f'{x},{y}') for n, (x, y) in norm.items()]
            drag['name'] = None
            change(changes)
        gesture.connect('drag-begin', begin)
        gesture.connect('drag-update', move)
        gesture.connect('drag-end', end)
        area.add_controller(gesture)
        s.append(area)

    def night(box):
        s = W.section(box, 'Night Shift')
        nl = displays.night_light()
        if nl['available'] is False:
            W.unavailable(s, 'Night colour is not available on this compositor.')
        W.switch_row(s, 'Warm the display colours', nl['active'], lambda v: ctx.do(displays.set_night_light, active=v, ok='Night Shift changed.'))
        W.choice_row(s, 'Schedule', [('Automatic', 'Sunset to sunrise'), ('Times', 'Custom times'), ('Constant', 'All day')], nl['mode'],
                     lambda v: ctx.do(displays.set_night_light, mode=v, ok='Schedule changed.'))
        W.scale_row(s, 'Warmth', 1200, 6500, 100, nl['night_temp'], lambda v: ctx.do(displays.set_night_light, night_temp=round(v), ok='Warmth changed.'),
                    fmt=lambda v: f'{int(v)} K', hint='Lower is warmer.')
        for key, label in (('evening', 'Starts at'), ('morning', 'Ends at')):
            e = Gtk.Entry(text=nl[key], width_chars=6, max_width_chars=6)
            e.connect('activate', lambda ent, key=key: ctx.do(displays.set_night_light, **{key: ent.get_text().strip()}, ok='Time saved.'))
            W.row(s, label + ' (custom times)', e, 'Press Return to save, for example 21:30.')
    reload()
