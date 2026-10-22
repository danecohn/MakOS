"""Security: screen lock, firewall (through the polkit helper), privacy indicators and permissions."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import ui
from ..backends import look, rootcall, security
from . import widgets as W


def build(col, ctx):
    d = ctx.data
    s = W.section(col, 'Screen lock')
    lock = security.lock_settings()
    W.switch_row(s, 'Lock the screen after being idle', lock['auto_lock'], lambda v: ctx.do(security.set_lock, auto_lock=v, ok='Saved.'))
    W.scale_row(s, 'Lock after', 1, 60, 1, lock['timeout_min'], lambda v: ctx.do(security.set_lock, timeout_min=round(v), ok='Idle time changed.'),
                fmt=lambda v: f'{int(v)} min')
    W.switch_row(s, 'Lock when the computer wakes from sleep', lock['lock_on_resume'], lambda v: ctx.do(security.set_lock, lock_on_resume=v, ok='Saved.'))
    W.button_row(s, 'Lock now', 'Lock Screen', lambda: ctx.do(security.lock_now, ok='Locking…'))
    W.note(s, 'The lock screen asks for your password itself; Settings never sees it.')

    s = W.section(col, 'Firewall')
    state = rootcall.firewall_state()
    if state is None:
        W.unavailable(s, 'The ufw firewall is not installed. Install it with: sudo apt install ufw')
    else:
        sw = W.switch_row(s, 'Firewall', state, lambda v: ctx.do(security.set_firewall, v, ok='Firewall updated.',
                                                              done=lambda r: _revert(sw, r, v)),
                          hint='Changing it asks for an administrator password through the system authentication dialog.')

    s = W.section(col, 'Privacy indicators')
    W.switch_row(s, 'Show camera, microphone and location use', d['privacy_indicators'],
                 lambda v: ctx.do(look.put, privacy_indicators=v, ok=ctx.saved('privacy_indicators')),
                 hint='The menu bar does not display these indicators yet; the live list below does work.')
    W.loading(s, security.indicators, _render_indicators)

    s = W.section(col, 'App permissions')

    def render_perms(box, perms):
        any_rows = False
        for p in perms:
            for app, value in sorted(p['apps'].items()):
                any_rows = True
                W.choice_row(box, f"{p['title']}: {app}", [('yes', 'Allowed'), ('no', 'Denied'), ('ask', 'Ask')], value,
                             lambda v, p=p, app=app: ctx.do(security.set_permission, p['table'], p['resource'], app, v, ok='Permission changed.'))
        if not any_rows:
            W.note(box, 'No applications have been granted or denied access yet.')
    W.loading(s, security.all_permissions, render_perms)


def _revert(sw, result, wanted):
    if result is False or (isinstance(result, dict) and not result.get('ok')):
        W.set_silent(sw, not wanted)


def _render_indicators(box, info):
    parts = []
    if info['camera']:
        parts.append('Camera: ' + ', '.join(info['camera']))
    if info['microphone']:
        parts.append('Microphone: ' + ', '.join(info['microphone']))
    if info['location']:
        parts.append('Location is in use')
    W.note(box, '\n'.join(parts) if parts else 'Nothing is using the camera, microphone or location right now.')
