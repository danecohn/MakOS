"""Users (AccountsService). Passwords are changed by the system `passwd` program in a terminal window, never in Settings."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk

from .. import ui
from ..backends import accounts
from . import widgets as W


def build(col, ctx):
    def load():
        return accounts.current()

    def render(box, me):
        s = W.section(box, 'Your account')
        W.note(s, f"Account name: {me['username']}    Type: " + ('Administrator' if me['admin'] else ('Standard' if me['admin'] is False else 'unknown')))
        name = Gtk.Entry(text=me['real_name'], width_chars=26)
        W.row(s, 'Full name', name)

        def save_name():
            try:
                ctx.do(accounts.set_real_name, name.get_text(), ok='Name changed.')
            except ValueError as error:
                ctx.flash(str(error), True)
        W.button_row(s, '', 'Save Name', save_name)

        def pick():
            dialog = Gtk.FileDialog(title='Choose a picture')

            def picked(dlg, result):
                try:
                    f = dlg.open_finish(result)
                except GLib.Error:
                    return
                if f and f.get_path():
                    ctx.do(accounts.set_picture, f.get_path(), ok='Picture changed.')
            dialog.open(ctx.window, None, picked)
        W.button_row(s, 'Picture', 'Choose Picture…', pick)
        s = W.section(box, 'Password')
        W.note(s, 'Your password is typed into the system passwd program in a terminal window. Settings never sees or stores it.')

        def passwd():
            if not accounts.change_password():
                ctx.flash('No terminal program was found. Open a terminal and run: passwd', True)
        W.button_row(s, '', 'Change Password…', passwd)
        s = W.section(box, 'Login')
        W.note(s, 'Automatic login: ' + ('on' if me['automatic_login'] else ('off' if me['automatic_login'] is False else 'unknown')) + '. Adding users and changing login options are not available in this build.')
    W.loading(col, load, render)
