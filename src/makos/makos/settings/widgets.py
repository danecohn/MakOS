"""Small GTK4 helpers shared by the panes (consistent rows, async loading, honest status lines)."""
import gi

gi.require_version('Gtk', '4.0')
import threading

from gi.repository import GLib, Gtk

from .. import ui


def page():
    return ui.box(True, 14)


def section(parent, title=None):
    box = ui.box(True, 6, 'settings-group')
    if title:
        box.append(Gtk.Label(label=title, xalign=0, css_classes=['section-title']))
    parent.append(box)
    return box


def note(parent, text, css='subtitle'):
    label = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=78, css_classes=[css], selectable=False)
    parent.append(label)
    return label


def unavailable(parent, text):
    """An honest 'this does not work here' line."""
    return note(parent, text, 'subtitle')


def row(parent, title, control=None, hint=None):
    line = ui.box(spacing=12)
    left = ui.box(True, 1)
    left.set_hexpand(True)
    left.append(Gtk.Label(label=title, xalign=0))
    if hint:
        left.append(Gtk.Label(label=hint, xalign=0, wrap=True, max_width_chars=60, css_classes=['subtitle']))
    line.append(left)
    if control is not None:
        control.set_valign(Gtk.Align.CENTER)
        line.append(control)
    parent.append(line)
    return line


def switch_row(parent, title, active, callback, hint=None, sensitive=True):
    sw = Gtk.Switch(active=bool(active), sensitive=sensitive)
    sw._silent = False
    sw.connect('notify::active', lambda s, _p: None if s._silent else callback(s.get_active()))
    row(parent, title, sw, hint)
    return sw


def set_silent(sw, value):
    """Change a switch without calling its callback (used to roll back a refused change)."""
    sw._silent = True
    sw.set_active(bool(value))
    sw._silent = False


def choice_row(parent, title, options, current, callback, hint=None):
    """options: [(value, label)]. Calls callback(value) on user changes only."""
    values = [v for v, _l in options]
    dd = Gtk.DropDown.new_from_strings([l for _v, l in options])
    if current in values:
        dd.set_selected(values.index(current))
    dd.connect('notify::selected', lambda d, _p: callback(values[d.get_selected()]) if d.get_selected() < len(values) else None)
    row(parent, title, dd, hint)
    return dd


def scale_row(parent, title, lo, hi, step, value, callback, hint=None, fmt=None, width=240):
    """Slider. callback fires once the user pauses (250 ms) so a drag does not run a command per pixel."""
    sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    sc.set_value(value)
    sc.set_size_request(width, -1)
    sc.set_draw_value(True)
    if fmt:
        sc.set_format_value_func(lambda _s, v: fmt(v))
    state = {'timer': 0}

    def changed(s):
        if state['timer']:
            GLib.source_remove(state['timer'])

        def fire():
            state['timer'] = 0
            callback(s.get_value())
            return False
        state['timer'] = GLib.timeout_add(250, fire)
    sc.connect('value-changed', changed)
    row(parent, title, sc, hint)
    return sc


def button_row(parent, title, label, callback, hint=None, css=None):
    b = ui.button(label, callback, css)
    row(parent, title, b, hint)
    return b


def run_async(fn, done, fail=None):
    """Run fn() on a worker thread; call done(result) (or fail(exc)) on the GTK main loop."""
    def work():
        try:
            result = fn()
        except Exception as error:  # noqa: BLE001 - shown to the user, never fatal
            if fail:
                GLib.idle_add(lambda e=error: (fail(e), False)[1])
            return
        GLib.idle_add(lambda: (done(result), False)[1])
    threading.Thread(target=work, daemon=True).start()


def loading(parent, loader, render, message='Reading system information…'):
    """Placeholder now; replaced by render(box, result) when the loader finishes. Failures say so plainly."""
    box = ui.box(True, 8)
    status = Gtk.Label(label=message, xalign=0, css_classes=['subtitle'])
    box.append(status)
    parent.append(box)

    def done(result):
        box.remove(status)
        render(box, result)

    def fail(error):
        status.set_text('This information is not available: ' + (str(error) or error.__class__.__name__)[:160])
    run_async(loader, done, fail)
    return box


def dialog(app, title, body, buttons):
    """Small message window. buttons: [(label, callback|None, css)]. Never contains password fields."""
    w = ui.window(app, title, 460, 200)
    col = ui.box(True, 16, 'sheet')
    col.append(Gtk.Label(label=body, wrap=True, max_width_chars=56, xalign=0))
    bar = ui.box(spacing=10)
    for label, cb, css in buttons:
        bar.append(ui.button(label, (lambda cb=cb: (cb() if cb else None, w.close())), css))
    col.append(bar)
    w.set_child(col)
    w.present()
    return w
