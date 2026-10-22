"""amerika-studio-approve: asks the user to approve one critical Studio tool call (code execution).

Called by amerika-studio-mcp: `--app A --tool T --summary S`, the code or arguments arrive on stdin. Exit 0 = approved,
anything else = declined. With no display or any error the answer is "no".
"""
import argparse
import sys

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import ui
from .common import APP_TITLES

TIMEOUT_S = 120


class ApproveApp(Gtk.Application):
    def __init__(self, args, detail):
        super().__init__(application_id='org.amerika.StudioApprove', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args, self.detail = args, detail
        self.verdict = 1

    def do_activate(self):
        ui.setup()
        win = Gtk.ApplicationWindow(application=self, title='Approve action')
        win.add_css_class('am-dialog')
        win.add_css_class('st-window')
        win.set_default_size(620, 420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(22)
        box.append(ui.label('AMERIKA AGENT WANTS TO RUN CODE', 'am-heading'))
        title = APP_TITLES.get(self.args.app, self.args.app)
        box.append(ui.label(f'In {title}: {self.args.tool}. {self.args.summary or ""}', 'am-sub', wrap=True))
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.add_css_class('am-term')
        view.get_buffer().set_text(self.detail[:20000])
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(view)
        box.append(scroll)
        row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        row.append(ui.button('Decline', 'am-secondary', lambda: self._finish(win, 1)))
        row.append(ui.button('Run it', 'am-primary', lambda: self._finish(win, 0)))
        box.append(row)
        win.set_child(box)
        win.connect('close-request', lambda *_: (setattr(self, 'verdict', 1), False)[1])
        GLib.timeout_add_seconds(TIMEOUT_S, lambda: (self._finish(win, 1), False)[1])
        win.present()

    def _finish(self, win, verdict):
        self.verdict = verdict
        win.destroy()
        self.quit()


def main(argv=None):
    p = argparse.ArgumentParser(prog='amerika-studio-approve')
    p.add_argument('--app', default='')
    p.add_argument('--tool', default='')
    p.add_argument('--summary', default='')
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    detail = sys.stdin.read()
    try:
        app = ApproveApp(args, detail)
        app.run([sys.argv[0]])
        return app.verdict
    except Exception:  # noqa: BLE001 - no display, no approval
        return 1


if __name__ == '__main__':
    sys.exit(main())
