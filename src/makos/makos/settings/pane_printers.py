"""Printers: CUPS queues, default printer, test page, print jobs."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import printers, sysutil
from . import widgets as W


def build(col, ctx):
    holder = ui.box(True, 12)
    col.append(holder)

    def load():
        if not printers.available():
            return None
        return {'printers': printers.printers(), 'jobs': printers.jobs()}

    def reload(_r=None):
        ui.clear(holder)
        W.loading(holder, load, render)

    def render(box, info):
        s = W.section(box, 'Printers')
        if info is None:
            W.unavailable(s, 'The CUPS print service is not running or not installed. Install it with: sudo apt install cups')
        elif not info['printers']:
            W.note(s, 'No printers are set up.')
        else:
            for p in info['printers']:
                line = ui.box(spacing=10)
                text = ui.box(True, 1)
                text.set_hexpand(True)
                text.append(Gtk.Label(label=p['name'] + ('  (default)' if p['default'] else ''), xalign=0))
                text.append(Gtk.Label(label=p['state'] + (' • network' if p['network'] else '') + (' • ' + p['reason'] if p['reason'] else ''), xalign=0, css_classes=['subtitle']))
                line.append(text)
                if not p['default']:
                    line.append(ui.button('Make Default', lambda p=p: ctx.do(printers.set_default, p['name'], ok='Default printer changed.', done=reload)))
                line.append(ui.button('Print Test Page', lambda p=p: ctx.do(printers.test_page, p['name'], ok='Test page sent.')))
                s.append(line)
        if info and info['jobs']:
            s = W.section(box, 'Print jobs')
            for j in info['jobs']:
                line = ui.box(spacing=10)
                line.append(Gtk.Label(label=f"{j['queue']} #{j['id']} ({j['user']}, {j['size']} bytes)", xalign=0, hexpand=True))
                line.append(ui.button('Cancel Job', lambda j=j: ctx.do(printers.cancel_job, j['queue'], j['id'], ok='Job cancelled.', done=reload)))
                s.append(line)
        s = W.section(box, 'Add a printer')
        W.note(s, 'Adding a printer needs administrator rights; the system printer tool asks for them itself.')
        W.button_row(s, '', 'Add Printer…', lambda: sysutil.popen(printers.add_printer_command()))
    reload()
