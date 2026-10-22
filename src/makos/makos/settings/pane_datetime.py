"""Date & Time (systemd-timedated via timedatectl)."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import datetime_, look
from . import widgets as W


def build(col, ctx):
    def load():
        return {'status': datetime_.status(), 'zones': datetime_.timezones()}

    def render(box, info):
        st = info['status']
        s = W.section(box, 'Date and time')
        if not st['available']:
            W.unavailable(s, 'The time service (systemd-timedated) is not available.')
            return
        W.note(s, 'Now: ' + (st['time'] or 'unknown'), 'title-label')
        W.switch_row(s, 'Set date and time automatically', st['ntp'], lambda v: ctx.do(datetime_.set_ntp, v, ok='Saved.'),
                     hint='Synchronised: ' + ('yes' if st['synchronized'] else 'not yet'), sensitive=st['can_ntp'])
        entry = Gtk.Entry(placeholder_text='2026-10-22 14:30', width_chars=18, sensitive=not st['ntp'])

        def set_time():
            try:
                ctx.do(datetime_.set_time, entry.get_text().strip(), ok='Time set.')
            except ValueError as error:
                ctx.flash(str(error), True)
        W.row(s, 'Set manually (automatic time must be off)', entry)
        W.button_row(s, '', 'Set Time', set_time).set_sensitive(not st['ntp'])
        s = W.section(box, 'Time zone')
        zones = info['zones']
        if zones:
            dd = Gtk.DropDown.new_from_strings(zones)
            dd.set_enable_search(True)
            if st['timezone'] in zones:
                dd.set_selected(zones.index(st['timezone']))
            dd.connect('notify::selected', lambda d, _p: ctx.do(datetime_.set_timezone, zones[d.get_selected()], ok='Time zone changed.'))
            W.row(s, 'Time zone', dd)
        else:
            W.note(s, 'Time zone: ' + (st['timezone'] or 'unknown'))
        s = W.section(box, 'Clock')
        W.switch_row(s, 'Use a 24-hour clock', st['clock_24h'], lambda v: ctx.do(datetime_.set_24h, v, ok=ctx.saved('clock_24h')))
    W.loading(col, load, render)
