"""amerika-studio-keys: the small dialog for the Anthropic key. The key is read once from a password entry, the entry is cleared
at once, and the key goes to the keyring helper (secret-tool, stdin) in a worker thread. The UI only ever shows saved / not saved."""
import argparse
import subprocess
import sys

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import common, keyring, ui
from .common import APP_TITLES, APPS, StudioError

CONSOLE_URL = 'https://console.anthropic.com/settings/keys'


class KeysWindow(Gtk.Window):
    """Set / remove the shared key (app=None) or one app's own key. `on_change` is called after a successful save/remove."""

    def __init__(self, app=None, parent=None, on_change=None, application=None):
        super().__init__(title='Anthropic key', transient_for=parent, modal=parent is not None, application=application)
        self.add_css_class('am-dialog')
        self.add_css_class('st-window')
        self.set_default_size(480, -1)
        self.set_resizable(False)
        self.app = app
        self.on_change = on_change
        who = APP_TITLES[app] if app else 'all Studio apps'
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(22)
        box.append(ui.label('ANTHROPIC KEY', 'am-heading'))
        box.append(ui.label(f'Used by {who}. Paste your key from console.anthropic.com. It is stored in your login keyring, '
                            'never in a file, never shown again, and the apps never see it (they talk to a local bridge).',
                            'am-sub', wrap=True))
        self.state = ui.label('', 'am-keystate')
        box.append(self.state)
        self.entry = Gtk.PasswordEntry(show_peek_icon=False, placeholder_text='sk-ant-...')
        self.entry.set_hexpand(True)
        self.entry.connect('activate', lambda *_: self.save())
        box.append(self.entry)
        self.msg = ui.label('', 'am-sub', wrap=True)
        box.append(self.msg)
        row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        link = ui.button('Get a key', 'st-link', lambda: Gio.AppInfo.launch_default_for_uri(CONSOLE_URL, None))
        self.remove_btn = ui.button('Remove', 'am-secondary', self.remove)
        self.save_btn = ui.button('Save key', 'am-primary', self.save)
        close = ui.button('Close', 'am-secondary', self.close)
        for w in (link, self.remove_btn, close, self.save_btn):
            row.append(w)
        box.append(row)
        self.set_child(box)
        self.refresh()

    def refresh(self):
        def work():
            return keyring.present(self.app)

        def done(has, err):
            self.state.set_label('Key saved in your keyring' if has else 'No key saved')
            self.state.remove_css_class('saved')
            if has:
                self.state.add_css_class('saved')
            self.remove_btn.set_sensitive(bool(has))
        ui.in_thread(work, done)

    def save(self):
        raw = self.entry.get_text()
        self.entry.set_text('')                     # the key leaves the widget immediately
        if not raw.strip():
            self.msg.set_label('Paste the key first.')
            return
        self.save_btn.set_sensitive(False)
        self.msg.set_label('Saving...')

        def work():
            keyring.store(raw, self.app)

        def done(_res, err):
            self.save_btn.set_sensitive(True)
            if err:
                self.msg.set_label(str(err) if isinstance(err, StudioError) else 'Could not save the key.')
                return
            self.msg.set_label('')
            self.refresh()
            if self.on_change:
                self.on_change()
        ui.in_thread(work, done)

    def remove(self):
        def done(_res, err):
            self.msg.set_label(str(err) if err else '')
            self.refresh()
            if self.on_change and not err:
                self.on_change()
        ui.in_thread(lambda: keyring.clear(self.app), done)


class KeysApp(Gtk.Application):
    def __init__(self, app):
        super().__init__(application_id='org.amerika.StudioKeys', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.target = app

    def do_activate(self):
        ui.setup()
        KeysWindow(self.target, application=self).present()


def main(argv=None):
    p = argparse.ArgumentParser(prog='amerika-studio-keys')
    p.add_argument('--app', choices=APPS)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    return KeysApp(args.app).run([sys.argv[0]])


if __name__ == '__main__':
    sys.exit(main())
