"""Original window chrome and common widgets for MakOS apps."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio
from . import common


def install_theme():
    # theme-and-system-skin: the complete widget theme (tokens, accent, Graphite) loads below glass.css.
    from . import appearance
    prefs = common.load_settings()
    appearance.install(Gdk.Display.get_default(), prefs.get('accent', 'blue'), bool(prefs.get('graphite')))
    provider = Gtk.CssProvider()
    provider.load_from_path(str(common.SHARE / 'theme/glass.css'))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    settings = Gtk.Settings.get_default()
    settings.set_property('gtk-font-name', 'DejaVu Sans 10')
    if settings.find_property('gtk-interface-color-scheme'):
        settings.set_property('gtk-interface-color-scheme', 1)
    else:
        settings.set_property('gtk-application-prefer-dark-theme', False)
    settings.set_property('gtk-enable-animations', not common.load_settings()['reduce_motion'])
    icons = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    icons.add_search_path(str(common.SHARE / 'icons'))
    settings.set_property('gtk-icon-theme-name', 'MakOS')
    refresh_appearance()  # settings-and-Seek: user-chosen font size / contrast / transparency (settings.model.css)
    return provider


_PREFS_PROVIDER = {}


def refresh_appearance():
    """(Re)load the user-preference override stylesheet above glass.css. Called at start-up and after Settings changes."""
    from .settings import model
    data = common.load_settings()
    display = Gdk.Display.get_default()
    provider = _PREFS_PROVIDER.get('p')
    if provider is None:
        provider = _PREFS_PROVIDER['p'] = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    provider.load_from_string(model.css(data))
    settings = Gtk.Settings.get_default()
    if settings.find_property('gtk-overlay-scrolling'):
        settings.set_property('gtk-overlay-scrolling', data['scrollbars'] == 'auto')
    from . import appearance
    appearance.set_variant(display, data['accent'], bool(data['graphite']))


def box(vertical=False, spacing=0, css=None):
    widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    if css:
        widget.add_css_class(css)
    return widget


def button(label, callback, css=None):
    widget = Gtk.Button(label=label)
    if css:
        widget.add_css_class(css)
    widget.connect('clicked', lambda *_: callback())
    return widget


def icon(name, size=48):
    path = common.SHARE / 'icons/MakOS/128x128/apps' / (name + '.png')
    if path.exists():
        img = Gtk.Image.new_from_file(str(path))
    else:
        img = Gtk.Image.new_from_icon_name('makos-' + name)
    img.set_pixel_size(size)
    return img


def clear(widget):
    child = widget.get_first_child()
    while child:
        next_child = child.get_next_sibling()
        widget.remove(child)
        child = next_child


def scroll(child, width=None, height=None):
    scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    scroller.set_child(child)
    if width:
        scroller.set_min_content_width(width)
    if height:
        scroller.set_min_content_height(height)
    return scroller


def window(app, title, width=820, height=550):
    w = Gtk.ApplicationWindow(application=app, title=title, default_width=width, default_height=height)
    bar = Gtk.HeaderBar(show_title_buttons=False)
    controls = box(spacing=7)
    for glyph, name, action in [('×', 'close', w.close), ('−', 'minimize', w.minimize),
                                  ('+', 'zoom', lambda: w.unmaximize() if w.is_maximized() else w.maximize())]:
        b = button(glyph, action, 'traffic')
        b.add_css_class(name + '-orb')
        b.set_valign(Gtk.Align.CENTER)
        b.set_tooltip_text({'close': 'Close', 'minimize': 'Minimize', 'zoom': 'Zoom'}[name])
        controls.append(b)
    bar.pack_start(controls)
    label = Gtk.Label(label=title, css_classes=['title-label'])
    bar.set_title_widget(label)
    w.set_titlebar(bar)
    if common.load_settings()['pinstripes']:
        w.add_css_class('pinstripes')
    w._bar, w._title = bar, label
    return w


def message(app, title, body):
    w = window(app, title, 460, 220)
    col = box(True, 16, 'sheet')
    col.append(Gtk.Label(label=body, wrap=True, max_width_chars=58, selectable=True))
    col.append(button('Done', w.close, 'suggested-action'))
    w.set_child(col)
    w.present()
    return w
