"""Widgets layer (Dashboard-style): Meta+F12 shows a translucent full-screen layer of small original widgets."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
from .. import ui
from . import store, cards

TITLE = 'Widgets'


class Context:
    def __init__(self, data, root):
        self.data, self.root = data, root

    def save(self):
        store.save(self.data)

    def alive(self):
        return self.root.get_mapped()


def is_open(shell):
    return bool(getattr(shell, 'overlay', None)) and shell.overlay.get_title() == TITLE


def toggle(shell):
    """Shell.action('widgets'): hotkey/menu toggles the layer."""
    if is_open(shell):
        shell.close_overlay()
    else:
        show(shell)


def show(shell):
    window = shell.new_overlay(TITLE, True)
    window.add_css_class('widget-layer')
    window.set_child(build(window))
    window.present()
    return window


def build(window):
    """Compose the layer into a widget tree; separate from the layer-shell window so the rig can render it."""
    data = store.load()
    root = Gtk.Overlay()
    root.add_css_class('widget-layer')
    ctx = Context(data, root)
    fixed = Gtk.Fixed(hexpand=True, vexpand=True)
    root.set_child(fixed)
    edit = {'on': False}
    closers = {}

    def place(kind, x, y):
        body = cards.BUILDERS[kind](ctx)
        card = ui.box(True, 6, 'widget-card')
        head = ui.box(spacing=6)
        title = Gtk.Label(label=store.KINDS[kind].upper(), xalign=0, hexpand=True, css_classes=['widget-title'])
        close = ui.button('✕', lambda k=kind, c=card: remove(k, c))
        close.set_visible(edit['on'])
        closers[kind] = close
        head.append(title)
        head.append(close)
        card.append(head)
        card.append(body)
        drag = Gtk.GestureDrag()
        origin = {}
        drag.connect('drag-begin', lambda *_: origin.update(zip('xy', fixed.get_child_position(card))) if hasattr(fixed, 'get_child_position') else None)

        def update(_g, dx, dy):
            if 'x' in origin:
                fixed.move(card, max(0, origin['x'] + dx), max(0, origin['y'] + dy))

        def end(_g, dx, dy):
            if 'x' in origin:
                store.move_widget(data, kind, origin['x'] + dx, origin['y'] + dy)
                ctx.save()
                origin.clear()
        drag.connect('drag-update', update)
        drag.connect('drag-end', end)
        head.add_controller(drag)
        card.kind = kind
        fixed.put(card, x, y)

    def remove(kind, card):
        store.remove_widget(data, kind)
        fixed.remove(card)
        closers.pop(kind, None)
        ctx.save()
        refill_menu()

    for w in data['widgets']:
        place(w['kind'], w['x'], w['y'])
    bar = ui.box(spacing=10, css='widget-bar')
    bar.set_halign(Gtk.Align.CENTER)
    bar.set_valign(Gtk.Align.END)
    bar.set_margin_bottom(36)
    add = Gtk.MenuButton(label='+ Add Widget')
    pop = Gtk.Popover()
    menu = ui.box(True, 2)
    pop.set_child(menu)
    add.set_popover(pop)

    def refill_menu():
        ui.clear(menu)
        have = {w['kind'] for w in data['widgets']}
        for kind, name in store.KINDS.items():
            if kind not in have:
                menu.append(ui.button(name, lambda k=kind: (pop.popdown(), store.add_widget(data, k, 80 + 30 * len(data['widgets']), 100 + 30 * len(data['widgets'])), place(k, 80 + 30 * (len(data['widgets']) - 1), 100 + 30 * (len(data['widgets']) - 1)), ctx.save(), refill_menu())))
        if not menu.get_first_child():
            menu.append(Gtk.Label(label='All widgets are on the layer'))
    refill_menu()

    def toggle_edit(btn):
        edit['on'] = btn.get_active()
        for c in closers.values():
            c.set_visible(edit['on'])
        btn.set_label('Done' if edit['on'] else 'Edit')
    editb = Gtk.ToggleButton(label='Edit')
    editb.connect('toggled', toggle_edit)
    bar.append(add)
    bar.append(editb)
    bar.append(Gtk.Label(label='Drag a widget by its title. Esc or the shortcut closes the layer.', css_classes=['hint']))
    root.add_overlay(bar)
    return root
