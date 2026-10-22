"""Mouse & Trackpad: tap to click, natural scrolling, pointer and scroll speed, with small animated previews of what each does."""
import gi

gi.require_version('Gtk', '4.0')
import math

from gi.repository import GLib, Gtk

from .. import ui
from ..backends import inputdev
from . import widgets as W


class Preview(Gtk.DrawingArea):
    """Tiny looping animation. kind: 'tap' (finger taps a pad) or 'scroll' (two fingers move; the page follows or opposes)."""

    def __init__(self, kind, natural=True):
        super().__init__(content_width=140, content_height=84)
        self.kind, self.natural, self.t = kind, natural, 0.0
        self.set_draw_func(self._draw)
        self._tick = self.add_tick_callback(self._advance)

    def _advance(self, _w, clock):
        settings = Gtk.Settings.get_default()
        self.t = (clock.get_frame_time() / 1e6) % 2.4 if settings.get_property('gtk-enable-animations') else 0.6
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgb(.92, .94, .97)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgb(.55, .62, .72)
        cr.rectangle(8, 8, w - 16, h - 16)
        cr.stroke()
        phase = self.t / 2.4
        if self.kind == 'tap':
            pulse = max(0.0, math.sin(phase * math.pi * 2))
            cr.set_source_rgba(.25, .5, .85, .25 + .55 * pulse)
            cr.arc(w / 2, h / 2, 10 + 8 * pulse, 0, 2 * math.pi)
            cr.fill()
        else:
            move = math.sin(phase * math.pi * 2) * 14
            cr.set_source_rgb(.25, .5, .85)
            for dx in (-8, 8):
                cr.arc(w / 2 + dx, h / 2 + move, 5, 0, 2 * math.pi)
                cr.fill()
            cr.set_source_rgb(.45, .5, .58)
            direction = 1 if self.natural else -1
            for i in range(4):
                y = (h / 2 + (i - 1.5) * 14 + move * direction) % (h - 16) + 8
                cr.rectangle(w - 34, y, 20, 4)
                cr.fill()


def build(col, ctx):
    devices = []
    holder = ui.box(True, 14)
    col.append(holder)

    def render(box, devs):
        if not devs:
            W.unavailable(box, 'No pointing devices were reported by the compositor (KWin InputDevice interface).')
            return
        for dev in devs:
            title = {'touchpad': 'Trackpad', 'mouse': 'Mouse', 'tablet': 'Tablet'}.get(dev['kind'], 'Pointer') + ': ' + dev['name']
            s = W.section(box, title)
            p, sup = dev['props'], dev['supported']

            def setter(prop, dev=dev):
                return lambda v: ctx.do(inputdev.set_device, dev, prop, v, ok='Saved.')
            if dev['kind'] == 'touchpad' and 'tapToClick' in p:
                row = ui.box(spacing=14)
                W.switch_row(s, 'Tap to click', p['tapToClick'], setter('tapToClick'))
                s.append(Preview('tap'))
            if 'naturalScroll' in p:
                prev = Preview('scroll', p['naturalScroll'])

                def natural(v, dev=dev, prev=prev):
                    prev.natural = v
                    ctx.do(inputdev.set_device, dev, 'naturalScroll', v, ok='Scroll direction changed.')
                W.switch_row(s, 'Natural scrolling', p['naturalScroll'], natural, hint='Content follows your fingers.')
                s.append(prev)
            if 'disableWhileTyping' in p:
                W.switch_row(s, 'Ignore the trackpad while typing', p['disableWhileTyping'], setter('disableWhileTyping'))
            if 'leftHanded' in p:
                W.switch_row(s, 'Left-handed (swap buttons)', p['leftHanded'], setter('leftHanded'))
            if 'pointerAcceleration' in p:
                W.scale_row(s, 'Pointer speed', -1.0, 1.0, 0.1, p['pointerAcceleration'], lambda v, dev=dev: ctx.do(inputdev.set_device, dev, 'pointerAcceleration', v, ok='Pointer speed changed.'),
                            fmt=lambda v: f'{v:+.1f}')
            if 'scrollFactor' in p:
                W.scale_row(s, 'Scrolling speed', 0.2, 4.0, 0.1, p['scrollFactor'], lambda v, dev=dev: ctx.do(inputdev.set_device, dev, 'scrollFactor', v, ok='Scroll speed changed.'),
                            fmt=lambda v: f'{v:.1f}×')
            if 'pointerAccelerationProfileFlat' in p:
                W.switch_row(s, 'Disable pointer acceleration', p['pointerAccelerationProfileFlat'], setter('pointerAccelerationProfileFlat'))
        W.note(box, 'Multi-finger swipe gestures are handled by the compositor and cannot be changed here yet.')
    W.loading(holder, inputdev.pointing_devices, render)
