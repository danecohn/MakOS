"""Sharing: honest status of the services that expose this computer. Nothing is switched on from here except user-level services."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import sharing
from . import widgets as W


def build(col, ctx):
    def load():
        return {'host': sharing.hostname(), 'services': sharing.status()}

    def render(box, info):
        s = W.section(box, 'This computer')
        W.note(s, 'Computer name: ' + (info['host'] or 'unknown'))
        s = W.section(box, 'Services')
        for svc in info['services']:
            if not svc['installed']:
                W.row(s, svc['name'], Gtk.Label(label='Not installed', css_classes=['subtitle']),
                      hint=('To turn on: ' + svc['how']) if svc['how'] else 'Not available on this computer.')
            elif svc['toggle']:
                W.switch_row(s, svc['name'], svc['active'], lambda v, svc=svc: ctx.do(sharing.set_user_service, svc['unit'], v, ok='Service changed.'))
            else:
                W.row(s, svc['name'], Gtk.Label(label='On' if svc['active'] else 'Off', css_classes=['subtitle']),
                      hint='Changing system services needs an administrator. Use: sudo systemctl ' + ('disable --now ' if svc['active'] else 'enable --now ') + svc['unit'])
        W.note(s, 'This pane reports status. It does not open any network port itself.')
    W.loading(col, load, render)
