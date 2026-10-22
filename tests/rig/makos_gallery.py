#!/usr/bin/env python3
"""Widget gallery: every standard widget in GTK 4 or GTK 3, as a *third-party* app would use them.

The theme is selected by the caller with GTK_THEME (MakOS, MakOS-Graphite, MakOS-Red ...),
exactly like a normal GTK application. Usage:
  GTK_THEME=MakOS python3 makos_gallery.py --gtk 4 [--snapshot out.png] [--hold SECONDS]
  --menu     open the popover/menu in the screenshot      --sheet  also show a message dialog
"""
import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--gtk', type=int, choices=(3, 4), default=4)
ap.add_argument('--snapshot')
ap.add_argument('--hold', type=float, default=0)
ap.add_argument('--menu', action='store_true')
ap.add_argument('--sheet', action='store_true')
ap.add_argument('--title', default='Widget Gallery')
ap.add_argument('--width', type=int, default=1380)
ap.add_argument('--height', type=int, default=880)
args = ap.parse_args()

import gi
if args.gtk == 4:
    gi.require_version('Gtk', '4.0')
else:
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, GLib, Gio, Gdk
G4 = args.gtk == 4
ROWS = [('Documents', 'folder'), ('Pictures', 'folder'), ('Music', 'folder'), ('Archive.zip', 'text-x-generic'),
        ('Report.txt', 'text-x-generic'), ('Notes.md', 'text-x-generic'), ('Photo.png', 'image-x-generic')]


def box(vertical=False, spacing=6, css=None):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    if css:
        b.get_style_context().add_class(css) if not G4 else b.add_css_class(css)
    return b


def add(parent, child, expand=False):
    if G4:
        if expand:
            child.set_hexpand(True) if parent.get_orientation() == Gtk.Orientation.HORIZONTAL else child.set_vexpand(True)
        parent.append(child)
    else:
        parent.pack_start(child, expand, expand, 0)
    return child


def css(widget, *names):
    for n in names:
        widget.add_css_class(n) if G4 else widget.get_style_context().add_class(n)


def heading(text):
    l = Gtk.Label(label=text, xalign=0)
    css(l, 'heading') if G4 else css(l, 'dim-label')
    return l


def section(title, *widgets):
    col = box(True, 6)
    add(col, heading(title))
    for w in widgets:
        add(col, w)
    return col


def row(*widgets, spacing=8):
    r = box(False, spacing)
    for w in widgets:
        add(r, w)
    return r


def linked(*widgets):
    r = box(False, 0, 'linked')
    for w in widgets:
        add(r, w)
    return r


def buttons():
    normal = Gtk.Button(label='Normal')
    default = Gtk.Button(label='Default'); css(default, 'suggested-action')
    destructive = Gtk.Button(label='Delete'); css(destructive, 'destructive-action')
    disabled = Gtk.Button(label='Disabled'); disabled.set_sensitive(False)
    flat = Gtk.Button(label='Flat'); css(flat, 'flat')
    circ = Gtk.Button.new_from_icon_name('list-add-symbolic') if G4 else Gtk.Button.new_from_icon_name('list-add-symbolic', Gtk.IconSize.BUTTON)
    css(circ, 'circular')
    toggle = Gtk.ToggleButton(label='Toggle'); toggle.set_active(True)
    seg = linked(*[Gtk.ToggleButton(label=t) for t in ('Icons', 'List', 'Columns')])
    seg_first = seg.get_first_child() if G4 else seg.get_children()[0]
    seg_first.set_active(True)
    link = Gtk.LinkButton.new_with_label('https://example.invalid/', 'Link button')
    return section('Buttons', row(normal, default, destructive, disabled), row(flat, circ, toggle, link), seg)


def toggles():
    c1 = Gtk.CheckButton(label='Unchecked')
    c2 = Gtk.CheckButton(label='Checked'); c2.set_active(True)
    c3 = Gtk.CheckButton(label='Mixed'); c3.set_inconsistent(True)
    c4 = Gtk.CheckButton(label='Disabled'); c4.set_active(True); c4.set_sensitive(False)
    r1 = Gtk.CheckButton(label='Radio A'); r2 = Gtk.CheckButton(label='Radio B') if G4 else Gtk.RadioButton.new_with_label_from_widget(r1 if False else None, 'x')
    if G4:
        r2.set_group(r1); r1.set_active(True); r3 = Gtk.CheckButton(label='Radio C'); r3.set_group(r1)
    else:
        r1 = Gtk.RadioButton.new_with_label(None, 'Radio A')
        r2 = Gtk.RadioButton.new_with_label_from_widget(r1, 'Radio B')
        r3 = Gtk.RadioButton.new_with_label_from_widget(r1, 'Radio C'); r3.set_sensitive(False)
    sw1 = Gtk.Switch(); sw2 = Gtk.Switch(); sw2.set_active(True); sw3 = Gtk.Switch(); sw3.set_sensitive(False)
    return section('Checks, radios and switches', row(c1, c2, c3, c4), row(r1, r2, r3), row(sw1, sw2, sw3))


def entries():
    plain = Gtk.Entry(); plain.set_text('Text entry')
    focused = Gtk.Entry(); focused.set_text('Focused (glow)')
    err = Gtk.Entry(); err.set_text('Error'); css(err, 'error')
    dis = Gtk.Entry(); dis.set_text('Disabled'); dis.set_sensitive(False)
    search = Gtk.SearchEntry(); search.set_text('Search')
    spin = Gtk.SpinButton.new_with_range(0, 100, 1); spin.set_value(42)
    spin2 = Gtk.SpinButton.new_with_range(0, 100, 1); spin2.set_sensitive(False)
    combo = Gtk.ComboBoxText(); [combo.append_text(t) for t in ('Combo box', 'Second', 'Third')]; combo.set_active(0)
    return section('Entries, spin buttons, combo boxes', plain, focused, err, dis, search, row(spin, spin2), combo), focused


def dropdown():
    if G4:
        dd = Gtk.DropDown.new_from_strings(['Drop down', 'Option two', 'Option three'])
    else:
        dd = Gtk.ComboBoxText(); [dd.append_text(t) for t in ('Drop down', 'Option two')]; dd.set_active(0)
    menu = Gio.Menu()
    menu.append('New Window', 'win.none'); menu.append('Open…', 'win.none'); menu.append('Close', 'win.none')
    mb = Gtk.MenuButton(label='Menu button')
    if G4:
        mb.set_menu_model(menu)
    else:
        m = Gtk.Menu()
        for t in ('New Window', 'Open…', 'Close'):
            m.append(Gtk.MenuItem(label=t))
        m.show_all(); mb.set_popup(m); mb._menu = m
    return row(dd, mb), mb


def ranges():
    s1 = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); s1.set_value(35); s1.set_size_request(240, -1)
    for v in (0, 50, 100):
        s1.add_mark(v, Gtk.PositionType.BOTTOM, str(v))
    s2 = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); s2.set_value(70); s2.set_sensitive(False); s2.set_size_request(240, -1)
    s3 = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1); s3.set_value(60); s3.set_size_request(-1, 90); s3.set_draw_value(False)
    p1 = Gtk.ProgressBar(); p1.set_fraction(.62); p1.set_show_text(True); p1.set_text('62%')
    p2 = Gtk.ProgressBar(); p2.set_fraction(.3)
    p3 = Gtk.ProgressBar(); p3.set_fraction(.9); p3.set_sensitive(False)
    lb = Gtk.LevelBar.new_for_interval(0, 10); lb.set_value(7)
    spinner = Gtk.Spinner(); spinner.start()
    return section('Scales, progress, level, spinner', row(s1, s3), s2, p1, p2, p3, lb, spinner)


def notebook():
    nb = Gtk.Notebook()
    for t in ('General', 'Advanced', 'About'):
        page = box(True, 6)
        add(page, Gtk.Label(label='%s page content' % t))
        add(page, Gtk.Entry())
        nb.append_page(page, Gtk.Label(label=t))
    nb.set_size_request(300, 110)
    exp = Gtk.Expander(label='Expander'); exp.set_expanded(True)
    exp.set_child(Gtk.Label(label='Hidden details', xalign=0)) if G4 else exp.add(Gtk.Label(label='Hidden details', xalign=0))
    fr = Gtk.Frame(label='Frame'); fr.set_child(Gtk.Label(label='Framed content', margin_top=6, margin_bottom=6)) if G4 else fr.add(Gtk.Label(label='Framed content', margin_top=6, margin_bottom=6))
    cal = Gtk.Calendar()
    return section('Notebook, expander, frame, calendar', nb, exp, fr, cal)


def lists():
    # ListBox, TreeView (alternating rows) and ColumnView
    store = Gtk.ListStore(str, str, int)
    for i, (name, _) in enumerate(ROWS):
        store.append([name, 'Folder' if i < 3 else 'Document', (i + 1) * 120])
    tree = Gtk.TreeView(model=store)
    tree.set_rules_hint(True) if not G4 else None
    for i, title in enumerate(('Name', 'Kind', 'Size')):
        tree.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i))
    tree.get_selection().select_path(Gtk.TreePath.new_from_string('1'))
    tw = Gtk.ScrolledWindow(); tw.set_min_content_height(170); tw.set_min_content_width(320)
    tw.set_child(tree) if G4 else tw.add(tree)
    css(tree, 'view') if False else None
    lbx = Gtk.ListBox(); css(lbx, 'boxed-list') if G4 else None
    for name, _ in ROWS[:4]:
        lbx.append(Gtk.Label(label=name, xalign=0, margin_top=4, margin_bottom=4, margin_start=8)) if G4 else lbx.add(Gtk.Label(label=name, xalign=0, margin_top=4, margin_bottom=4, margin_start=8))
    if not G4:
        lbx.show_all()
    lbx.select_row(lbx.get_row_at_index(1))
    out = [section('Tree view with alternating rows', tw), section('List box', lbx)]
    if G4:
        sel = Gtk.SingleSelection(model=Gtk.StringList.new([n for n, _ in ROWS]))
        lv = Gtk.ListView(model=sel, factory=Gtk.SignalListItemFactory())
        fac = lv.get_factory()
        fac.connect('setup', lambda f, item: item.set_child(Gtk.Label(xalign=0)))
        fac.connect('bind', lambda f, item: item.get_child().set_label(item.get_item().get_string()))
        lv.add_css_class('alternating') if False else None
        lw = Gtk.ScrolledWindow(); lw.set_min_content_height(110); lw.set_child(lv)
        out.append(section('List view', lw))
    return out


def sidebar():
    lbx = Gtk.ListBox(); css(lbx, 'navigation-sidebar') if G4 else css(lbx, 'sidebar')
    for name in ('PLACES', 'Home', 'Desktop', 'Documents', 'Downloads', 'DEVICES', 'Computer'):
        l = Gtk.Label(label=name, xalign=0, margin_top=3, margin_bottom=3)
        if name.isupper():
            css(l, 'dim-label')
        lbx.append(l) if G4 else lbx.add(l)
    if not G4:
        lbx.show_all()
    lbx.select_row(lbx.get_row_at_index(3))
    sw = Gtk.ScrolledWindow(); sw.set_size_request(170, -1)
    sw.set_child(lbx) if G4 else sw.add(lbx)
    css(sw, 'sidebar') if False else None
    return sw


def text_area():
    tv = Gtk.TextView(); tv.get_buffer().set_text('A multi-line text view.\nSecond line with selected text.')
    tv.set_size_request(300, 60)
    fr = Gtk.Frame(); fr.set_child(tv) if G4 else fr.add(tv)
    tip = Gtk.Button(label='Hover for tooltip'); tip.set_tooltip_text('Tooltip: glass and metal')
    sb = Gtk.Scrollbar(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=20, lower=0, upper=100, page_size=30))
    sbv = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=Gtk.Adjustment(value=10, lower=0, upper=100, page_size=30)); sbv.set_size_request(-1, 60)
    sep = Gtk.Separator()
    return section('Text, tooltip, scrollbars', fr, tip, sb, row(sbv), sep)


def build():
    win = Gtk.Window(title=args.title)
    win.set_default_size(args.width, args.height)
    hb = Gtk.HeaderBar()
    if G4:
        win.set_titlebar(hb)
        tb = Gtk.Button.new_from_icon_name('view-refresh-symbolic'); hb.pack_end(tb)
    else:
        hb.set_show_close_button(True); hb.set_title(args.title); hb.set_subtitle('GTK 3')
        win.set_titlebar(hb)
        tb = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON); hb.pack_end(tb)
    root = box(True, 0)
    # toolbar
    toolbar = box(False, 8, 'toolbar')
    add(toolbar, linked(*[Gtk.ToggleButton(label=t) for t in ('Back', 'Forward')]))
    fl = Gtk.Button(label='Flat tool'); css(fl, 'flat'); add(toolbar, fl)
    ent = Gtk.SearchEntry(); add(toolbar, ent, True)
    dd, mb = dropdown(); add(toolbar, dd)
    add(root, toolbar)
    body = box(False, 0)
    add(body, sidebar())
    add(body, Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
    cols = box(False, 22)
    for w in cols.get_children() if not G4 else []:
        pass
    ent_section, focused = entries()
    c1 = box(True, 16); [add(c1, w) for w in (buttons(), toggles(), ent_section, text_area())]
    c2 = box(True, 16); [add(c2, w) for w in (ranges(), notebook())]
    c3 = box(True, 16); [add(c3, w) for w in lists()]
    for c in (c1, c2, c3):
        c.set_margin_top(14); c.set_margin_bottom(14); c.set_margin_start(8); c.set_margin_end(8)
        add(cols, c)
    sc = Gtk.ScrolledWindow(); sc.set_child(cols) if G4 else sc.add(cols)
    add(body, sc, True)
    add(root, body, True)
    st = Gtk.Label(label='Status bar: 7 items', xalign=0); css(st, 'statusbar'); add(root, st)
    win.set_child(root) if G4 else win.add(root)
    return win, focused, mb


def snapshot(win, path):
    if G4:
        w, h = win.get_width(), win.get_height()
        paintable = Gtk.WidgetPaintable.new(win)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w, h)
        node = snap.to_node()
        texture = win.get_native().get_renderer().render_texture(node, None)
        texture.save_to_png(path)
    else:
        import cairo
        w, h = win.get_allocated_width(), win.get_allocated_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        win.draw(cairo.Context(surface))
        surface.write_to_png(path)


def main():
    app = Gtk.Application(application_id='org.makos.Gallery%d' % args.gtk) if G4 else None
    def show(*_):
        win, focused, mb = build()
        if G4:
            win.set_application(app) if app else None
            win.present()
            win.set_focus_visible(True)
        else:
            win.show_all()
        focused.grab_focus()
        def later():
            if args.menu:
                (mb.popup() if G4 else mb._menu.popup_at_widget(mb, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None))
            if args.sheet:
                dlg = Gtk.MessageDialog(transient_for=win, modal=False, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
                                        text='Save changes to "Report"?', secondary_text='Your changes will be lost if you do not save them.') if not G4 else Gtk.Window(title='Sheet')
                if G4:
                    dlg = Gtk.AlertDialog(message='Save changes to "Report"?', detail='Your changes will be lost if you do not save them.', buttons=['Cancel', 'Save'], default_button=1, cancel_button=0)
                    dlg.choose(win, None, lambda *a: None)
                else:
                    dlg.add_button('Cancel', 0); dlg.add_button('Save', 1)
                    dlg.set_default_response(1); dlg.show()
            return False
        GLib.timeout_add(700, later)
        if args.snapshot:
            def shot():
                snapshot(win, args.snapshot)
                (app.quit() if app else Gtk.main_quit())
                return False
            GLib.timeout_add(1800, shot)
        elif args.hold:
            GLib.timeout_add(int(args.hold * 1000), lambda: (app.quit() if app else Gtk.main_quit()))
    if G4:
        app.connect('activate', show)
        return app.run([sys.argv[0]])
    show()
    Gtk.main()
    return 0


sys.exit(main())
