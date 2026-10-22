"""A plain coloured GTK4 window used as a stand-in application by the rig: makos_launcher_window.py APP_ID TITLE COLOR [W H]."""
import sys

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk  # noqa: E402

app_id, title, color = sys.argv[1], sys.argv[2], sys.argv[3]
w, h = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else (640, 420)
fullscreen = 'fullscreen' in sys.argv


def activate(app):
    win = Gtk.ApplicationWindow(application=app, title=title, default_width=w, default_height=h)
    label = Gtk.Label(label=title)
    label.add_css_class('big')
    win.set_child(label)
    css = Gtk.CssProvider()
    css.load_from_string('window { background: %s; } label.big { font-size: 42px; font-weight: bold; color: white; }' % color)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    win.present()
    if fullscreen:
        win.fullscreen()


app = Gtk.Application(application_id=app_id)
app.connect('activate', activate)
app.run([])
