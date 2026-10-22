"""MakOS Settings: dedicated preferences, existing read-only hardware backends."""
import json
import threading
from gi.repository import Gtk, GLib
from . import common, ui
from .backends import audio, netman, bluetooth, displays, storage, accounts, printers

GROUPS = [
 ('Personal', [('Appearance','settings'),('Desktop & Screen Saver','photos'),('Launcher Bar','desktops'),('Desks & Spread','spread'),('Language & Text','text-editor'),('Security','drive-internal')]),
 ('Hardware', [('Displays','desktops'),('Keyboard','text-editor'),('Mouse & Trackpad','settings'),('Sound','music'),('Energy Saver','activity'),('Printers','file-document')]),
 ('Internet & Wireless', [('Bluetooth','settings'),('Network','browser'),('Sharing','folder-network')]),
 ('System', [('Users','contacts'),('Date & Time','clock'),('Software Update','software-center'),('Accessibility','settings'),('Startup','drive-internal'),('Rewind','rewind')])]

class Settings:
    def __init__(self, app):
        self.app = app
        self.win = ui.window(app, 'Settings', 790, 650)
        self.data = common.load_settings()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.win._bar.pack_start(ui.button('Show All', lambda: self.stack.set_visible_child_name('all')))
        self.all = ui.box(True, 0)
        for title, panes in GROUPS:
            section = ui.box(True, 4, 'settings-section')
            section.append(Gtk.Label(label=title, xalign=0, css_classes=['section-title']))
            grid = Gtk.Grid(column_spacing=3, row_spacing=3, column_homogeneous=True)
            for n, (name, symbol) in enumerate(panes):
                tile = ui.box(True, 7)
                tile.append(ui.icon(symbol, 48))
                tile.append(Gtk.Label(label=name, wrap=True, max_width_chars=17, justify=Gtk.Justification.CENTER))
                b = ui.button('', lambda name=name: self.pane(name), 'settings-tile')
                b.set_child(tile)
                b.set_size_request(116, 95)
                grid.attach(b, n % 6, n // 6, 1, 1)
            section.append(grid)
            self.all.append(section)
            self.all.append(Gtk.Separator())
        self.stack.add_named(ui.scroll(self.all), 'all')
        self.win.set_child(self.stack)
        self.win.present()

    def save(self):
        common.save_settings(self.data)
        if hasattr(self.app, 'reload_preferences'):
            self.app.reload_preferences()

    def toggle(self, col, title, key):
        check = Gtk.CheckButton(label=title, active=bool(self.data[key]))
        check.connect('toggled', lambda c: (self.data.update({key:c.get_active()}),self.save()))
        col.append(check)

    def pane(self, title):
        old = self.stack.get_child_by_name('pane')
        if old:
            self.stack.remove(old)
        col = ui.box(True, 18, 'sheet')
        col.append(Gtk.Label(label=title, xalign=0, css_classes=['hero']))
        if title == 'Appearance':
            col.append(Gtk.Label(label='Glass & Metal', xalign=0, css_classes=['title-label']))
            self.toggle(col, 'Use pinstripe window backgrounds', 'pinstripes')
            self.toggle(col, 'Reduce motion', 'reduce_motion')
            row = ui.box(spacing=12)
            row.append(ui.button('Cancel', lambda: self.stack.set_visible_child_name('all')))
            row.append(ui.button('Default button', lambda: None, 'suggested-action'))
            col.append(row)
            col.append(Gtk.Entry(placeholder_text='Inset text field'))
            col.append(Gtk.Label(label='DejaVu Sans • open font supplied by Ubuntu', xalign=0, css_classes=['subtitle']))
        elif title == 'Launcher Bar':
            col.append(Gtk.Label(label='Icon size', xalign=0))
            size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 32, 96, 1)
            size.set_value(self.data['launcher_size'])
            size.connect('value-changed', lambda s: (self.data.update(launcher_size=round(s.get_value())), self.save()))
            col.append(size)
            pos = Gtk.DropDown.new_from_strings(['Bottom','Left','Right'])
            pos.set_selected(['bottom','left','right'].index(self.data['launcher_position']))
            pos.connect('notify::selected', lambda p, _ps: (self.data.update(launcher_position=['bottom','left','right'][p.get_selected()]),self.save()))
            col.append(pos)
            self.toggle(col, 'Automatically hide the launcher bar', 'launcher_autohide')
        elif title == 'Startup':
            col.append(Gtk.Label(label='MakOS is a separate login session. Login and boot theme switching is not enabled in this development build. Your existing sessions are preserved.', wrap=True, xalign=0))
        elif title == 'Rewind':
            col.append(Gtk.Label(label='Backup integration is not implemented in this development build. No backup or restore jobs have been created.', wrap=True, xalign=0))
        else:
            readers = {'Sound': audio.devices, 'Network': netman.wifi_list, 'Bluetooth': bluetooth.devices,
                       'Displays': displays.outputs, 'Printers': printers.printers, 'Users': accounts.current,
                       'Energy Saver': lambda: {'battery': self.app.status.get('battery') if hasattr(self.app,'status') else None},
                       'Sharing': storage.volumes}
            if title in readers:
                report = Gtk.Label(label='Reading system information…', xalign=0, yalign=0, selectable=True, wrap=True)
                col.append(report)
                def work():
                    try:
                        value = json.dumps(readers[title](), indent=2, ensure_ascii=False)
                    except Exception:
                        value = 'System service unavailable.'
                    GLib.idle_add(lambda: (report.set_text(value or 'No devices reported.'),False)[1])
                threading.Thread(target=work, daemon=True).start()
                col.append(Gtk.Label(label='Read-only status in this development build.',xalign=0,css_classes=['subtitle']))
            else:
                col.append(Gtk.Label(label='This pane is not implemented yet.',xalign=0))
        self.stack.add_named(ui.scroll(col), 'pane')
        self.stack.set_visible_child_name('pane')
