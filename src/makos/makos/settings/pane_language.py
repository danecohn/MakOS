"""Language & Text: display language and formats, keyboard layouts, text replacement list."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import common, ui
from ..backends import inputdev, language, look
from . import model, widgets as W


def build(col, ctx):
    s = W.section(col, 'Language and region')
    W.note(s, 'Takes effect at your next login. It is written to ~/.config/environment.d, never to system files.')
    user = language.user_settings()

    def load():
        names = language.installed()
        return {'locales': names, 'system': language.system_locale()}

    def render(box, info):
        locales = info['locales']
        if not locales:
            W.unavailable(box, 'No UTF-8 locales are installed. Install more with: sudo dpkg-reconfigure locales')
            return
        options = [(n, language.describe(n)) for n in locales]
        cur = user['lang'] if user['lang'] in locales else (info['system'] if info['system'] in locales else locales[0])
        W.choice_row(box, 'Language', options, cur, lambda v: ctx.do(language.set_language, v, ok='Language saved for your next login.'))
        W.choice_row(box, 'Region formats (dates, numbers, currency)', options,
                     user['LC_TIME'] if user['LC_TIME'] in locales else cur,
                     lambda v: ctx.do(language.set_all_formats, v, ok='Formats saved for your next login.'))
        W.note(box, 'System-wide locale: ' + (info['system'] or 'unknown'))
    W.loading(s, load, render)

    s = W.section(col, 'Keyboard layouts')
    layouts_box = ui.box(True, 4)
    s.append(layouts_box)
    names, variants = inputdev.available_layouts()
    name_of = dict(names)

    def refresh():
        ui.clear(layouts_box)
        cur = inputdev.layouts()
        for i, item in enumerate(cur):
            line = ui.box(spacing=8)
            label = name_of.get(item['layout'], item['layout']) + (f" ({item['variant']})" if item['variant'] else '')
            line.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            line.append(ui.button('Up', lambda i=i: act(inputdev.move_layout, i, -1)))
            line.append(ui.button('Down', lambda i=i: act(inputdev.move_layout, i, 1)))
            rm = ui.button('Remove', lambda i=i: act(inputdev.remove_layout, i))
            rm.set_sensitive(len(cur) > 1)
            line.append(rm)
            layouts_box.append(line)

    def act(fn, *args):
        ctx.do(fn, *args, ok='Keyboard layouts changed.', done=lambda _r: refresh())
    refresh()
    codes = [c for c, _n in names]
    add = Gtk.DropDown.new_from_strings([n for _c, n in names])
    add.set_enable_search(True)
    line = ui.box(spacing=8)
    line.append(add)
    line.append(ui.button('Add Layout', lambda: act(inputdev.add_layout, codes[add.get_selected()]) if codes else None))
    s.append(line)
    W.choice_row(s, 'Switch layouts with', inputdev.SWITCH_OPTIONS, inputdev.switch_shortcut(),
                 lambda v: ctx.do(inputdev.set_switch_shortcut, v, ok='Saved.'))

    s = W.section(col, 'Text replacement')
    W.note(s, 'Typing a trigger followed by a space or return in a VigilOS text field (Text Editor, Notes) replaces it. Other applications are not affected.')
    box = ui.box(True, 4)
    s.append(box)
    state = {'items': common.load_settings()['text_replacements']}

    def save(items):
        items = model.clean_replacements(items)
        state['items'] = items
        ctx.do(look.put, text_replacements=items, ok='Saved.', done=lambda _r: draw())

    def draw():
        ui.clear(box)
        for src, dst in state['items']:
            line = ui.box(spacing=8)
            line.append(Gtk.Label(label=src, xalign=0, width_chars=14))
            line.append(Gtk.Label(label='→', css_classes=['subtitle']))
            line.append(Gtk.Label(label=dst, xalign=0, hexpand=True, ellipsize=3))
            line.append(ui.button('Delete', lambda s_=src: save([i for i in state['items'] if i[0] != s_])))
            box.append(line)
        if not state['items']:
            box.append(Gtk.Label(label='No replacements yet.', xalign=0, css_classes=['subtitle']))
    draw()
    trig = Gtk.Entry(placeholder_text='Replace', width_chars=12)
    repl = Gtk.Entry(placeholder_text='With', hexpand=True)
    line = ui.box(spacing=8)
    line.append(trig)
    line.append(repl)

    def add_item():
        t, r = trig.get_text().strip(), repl.get_text()
        if not t or not r or ' ' in t:
            ctx.flash('Enter a trigger without spaces and its replacement.', True)
            return
        save(state['items'] + [[t, r]])
        trig.set_text('')
        repl.set_text('')
    line.append(ui.button('Add', add_item))
    s.append(line)
