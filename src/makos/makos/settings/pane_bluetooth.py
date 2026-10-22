"""Bluetooth (BlueZ): power, discovery, pair, connect, disconnect, forget."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import bluetooth
from . import widgets as W


def build(col, ctx):
    holder = ui.box(True, 12)
    col.append(holder)

    def load():
        a = bluetooth.adapter()
        return {'adapter': a, 'devices': bluetooth.devices() if a else []}

    def reload(_r=None):
        ui.clear(holder)
        W.loading(holder, load, render)

    def render(box, info):
        a = info['adapter']
        s = W.section(box, 'Bluetooth')
        if not a:
            W.unavailable(s, 'No Bluetooth adapter was found, or the Bluetooth service is not running.')
            return
        W.switch_row(s, 'Bluetooth: ' + a['name'], a['powered'], lambda v: ctx.do(bluetooth.set_power, v, ok='Bluetooth ' + ('on.' if v else 'off.'), done=reload))
        if not a['powered']:
            return
        W.switch_row(s, 'Look for nearby devices', a['discovering'], lambda v: ctx.do(bluetooth.scan, v, ok='Searching…' if v else 'Stopped searching.', done=reload))
        s = W.section(box, 'Devices')
        if not info['devices']:
            W.note(s, 'No devices found yet. Put the device in pairing mode and search again.')
        for d in info['devices']:
            line = ui.box(spacing=10)
            text = ui.box(True, 1)
            text.set_hexpand(True)
            text.append(Gtk.Label(label=d['name'], xalign=0))
            state = 'Connected' if d['connected'] else ('Paired' if d['paired'] else 'Not paired')
            if d['battery'] is not None:
                state += f" • battery {d['battery']} %"
            text.append(Gtk.Label(label=d['kind'] + ' • ' + state, xalign=0, css_classes=['subtitle']))
            line.append(text)
            mac = d['address']
            if d['paired']:
                if d['connected']:
                    line.append(ui.button('Disconnect', lambda m=mac: ctx.do(bluetooth.disconnect, m, ok='Disconnected.', done=reload)))
                else:
                    line.append(ui.button('Connect', lambda m=mac: ctx.do(bluetooth.connect, m, ok='Connected.', done=reload)))
                line.append(ui.button('Forget', lambda m=mac: ctx.do(bluetooth.forget, m, ok='Device removed.', done=reload)))
            else:
                line.append(ui.button('Pair', lambda m=mac: ctx.do(bluetooth.pair, m, ok='Paired and connected.', done=reload), 'suggested-action'))
            s.append(line)
        W.note(s, 'Pairing uses simple “just works” pairing. Devices that ask for a PIN are not supported yet.')
        W.button_row(s, '', 'Refresh', reload)
    reload()
