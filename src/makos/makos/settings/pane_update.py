"""Software Update: apt state; refresh and upgrade only through the polkit helper (fixed arguments, no dist-upgrade)."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import updates
from . import widgets as W


def build(col, ctx):
    holder = ui.box(True, 12)
    col.append(holder)

    def reload(_r=None):
        ui.clear(holder)
        W.loading(holder, updates.status, render, 'Checking for updates…')

    def run(fn, message):
        ctx.flash(message + ' This can take several minutes.')
        ctx.do(fn, ok=lambda r: 'Done.', done=reload)

    def render(box, st):
        s = W.section(box, 'Updates')
        W.note(s, f"{st['count']} update{'s' if st['count'] != 1 else ''} available" + (f", {st['security']} security" if st['security'] else '')
               + '. Package lists refreshed ' + updates.ago(st['last_refresh']) + '.', 'title-label')
        if st['reboot_required']:
            W.note(s, 'A restart is needed to finish a previous update.')
        W.button_row(s, 'Check for updates', 'Check Now', lambda: run(updates.refresh, 'Refreshing package lists.'),
                     hint='Asks for an administrator password through the system authentication dialog.')
        if st['count']:
            def confirm():
                W.dialog(ctx.app, 'Install updates', f"Install {st['count']} updates? Packages are upgraded but never removed, and your login manager is kept as it is.",
                         [('Cancel', None, None), ('Install', lambda: run(updates.upgrade, 'Installing updates.'), 'suggested-action')])
            W.button_row(s, 'Install', 'Install Updates…', confirm, css='suggested-action')
        if st['upgradable']:
            s = W.section(box, 'Available')
            for u in st['upgradable'][:40]:
                W.note(s, f"{u['name']}   {u['old']} → {u['new']}" + ('   (security)' if u['security'] else ''))
            if len(st['upgradable']) > 40:
                W.note(s, f"…and {len(st['upgradable']) - 40} more.")
    reload()
