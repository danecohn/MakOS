"""Small helpers over gtk4-layer-shell."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402

try:
    gi.require_version('Gtk4LayerShell', '1.0')
    from gi.repository import Gtk4LayerShell as LS  # noqa: E402
except (ValueError, ImportError):  # running outside a layer-shell compositor setup (e.g. tests)
    LS = None


def available():
    return LS is not None and LS.is_supported()


def setup(window, layer, anchors=(), margins=None, exclusive=None, keyboard=None, namespace='amerika'):
    """Turn a Gtk.Window into a layer-shell surface. `anchors` is an iterable of 'top','bottom','left','right'."""
    if LS is None:
        return False
    LS.init_for_window(window)
    LS.set_namespace(window, namespace)
    LS.set_layer(window, {'background': LS.Layer.BACKGROUND, 'bottom': LS.Layer.BOTTOM, 'top': LS.Layer.TOP,
                          'overlay': LS.Layer.OVERLAY}[layer])
    for name, edge in (('top', LS.Edge.TOP), ('bottom', LS.Edge.BOTTOM), ('left', LS.Edge.LEFT), ('right', LS.Edge.RIGHT)):
        LS.set_anchor(window, edge, name in anchors)
    for name, value in (margins or {}).items():
        LS.set_margin(window, {'top': LS.Edge.TOP, 'bottom': LS.Edge.BOTTOM, 'left': LS.Edge.LEFT, 'right': LS.Edge.RIGHT}[name], value)
    if exclusive == 'auto':
        LS.auto_exclusive_zone_enable(window)
    elif isinstance(exclusive, int):
        LS.set_exclusive_zone(window, exclusive)
    if keyboard:
        LS.set_keyboard_mode(window, {'none': LS.KeyboardMode.NONE, 'exclusive': LS.KeyboardMode.EXCLUSIVE,
                                      'on_demand': LS.KeyboardMode.ON_DEMAND}[keyboard])
    return True
