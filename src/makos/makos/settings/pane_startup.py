"""Startup: login items, and an honest note that login/boot theme switches are not available."""
from ..backends import startup
from . import widgets as W


def build(col, ctx):
    s = W.section(col, 'Login items')
    W.note(s, 'Applications that start when you log in (XDG autostart). Switching one off only affects your account.')

    def render(box, items):
        if not items:
            W.note(box, 'No login items.')
        for it in items:
            W.switch_row(box, it['name'], it['enabled'], lambda v, it=it: ctx.do(startup.set_item_enabled, it['id'], v, ok='Saved.'),
                         hint=('System item • ' if it['system'] else '') + it['exec'][:70])
    W.loading(s, startup.login_items, render)
    s = W.section(col, 'Login screen and boot splash')
    W.unavailable(s, startup.theme_switch_status()['reason'])
