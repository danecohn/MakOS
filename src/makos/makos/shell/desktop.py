"""The desktop layer: a background layer-shell window showing the wallpaper.

Why the rig showed a white desktop: the build step copies assets/makos/wallpaper-aurora-blue.png into
src/makos/wallpapers/, which does not exist in a plain source checkout, so the shell fell back to a label on the default
window colour. `wallpaper_path` now also looks in the repository's assets directory, and a missing image falls back to a
painted gradient instead of white.
"""
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402

from .. import common

DEFAULT_NAME = 'wallpaper-aurora-blue.png'
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp')


def wallpaper_path(prefs=None):
    """The image to show: the user's choice, else the shipped wallpaper (installed share dir, then the source tree's
    assets/ directory), else None."""
    chosen = (prefs or {}).get('wallpaper') or ''
    if chosen:
        p = Path(chosen)
        if p.is_file() and p.suffix.lower() in IMAGE_EXT:
            return p
    for base in (common.SHARE / 'wallpapers', common.SOURCE.parents[1] / 'assets' / 'makos'):
        p = base / DEFAULT_NAME
        if p.is_file():
            return p
    return None


class DesktopLayer:
    """Owns the picture widget inside the shell's background surface and swaps images when the preference changes."""

    def __init__(self, window, prefs):
        self.window = window
        self.path = None
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, hexpand=True, vexpand=True)
        self.picture.add_css_class('desktop-picture')
        window.add_css_class('desktop-layer')
        window.set_child(self.picture)
        self.update(prefs)

    def update(self, prefs):
        path = wallpaper_path(prefs)
        if path == self.path:
            return
        self.path = path
        if path is None:
            self.picture.set_paintable(None)
            return
        try:
            self.picture.set_filename(str(path))
        except Exception as error:  # a corrupt user image must never take the desktop down
            print('wallpaper not loaded:', type(error).__name__, flush=True)
            self.path = None
            self.picture.set_paintable(None)
