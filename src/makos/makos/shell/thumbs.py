"""Window thumbnails: KWin ScreenShot2 per window, downscaled off the main thread and cached as GPU-friendly textures.

Used by Spread, Desks and the minimized-window items of the Launcher Bar. A window that is minimized (or on another desk)
cannot always be captured, so the last good thumbnail is kept and reused until a fresh one arrives.
"""
import threading
import time

import gi

gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib  # noqa: E402

try:
    import cairo
except ImportError:  # pragma: no cover - the shell needs cairo anyway
    cairo = None

MAX_SIDE = 960


def _shrink(surface, max_side=MAX_SIDE):
    """Downscale a cairo ImageSurface so its longest side is at most `max_side`. Returns (bytes, w, h, stride, premultiplied)."""
    w, h = surface.get_width(), surface.get_height()
    s = min(1.0, max_side / max(w, h))
    if s < 1.0:
        nw, nh = max(1, round(w * s)), max(1, round(h * s))
        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, nw, nh)
        ctx = cairo.Context(small)
        ctx.scale(nw / w, nh / h)
        ctx.set_source_surface(surface, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_BEST)
        ctx.paint()
        small.flush()
        return bytes(small.get_data()), nw, nh, small.get_stride()
    surface.flush()
    return bytes(surface.get_data()), w, h, surface.get_stride()


def texture_from(data, w, h, stride):
    return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, GLib.Bytes.new(data), stride)


class Thumbs:
    """id -> (texture, aspect, time). `request(ids)` captures in worker threads and calls `on_update` on the main loop."""

    def __init__(self, bus, on_update=None):
        self.bus = bus
        self.on_update = on_update
        self.cache = {}
        self._busy = set()
        self._lock = threading.Lock()
        self.failures = {}

    def get(self, win_id):
        entry = self.cache.get(str(win_id))
        return entry[0] if entry else None

    def aspect(self, win_id, default=4 / 3):
        entry = self.cache.get(str(win_id))
        return entry[1] if entry else default

    def request(self, win_ids):
        for ident in win_ids:
            ident = str(ident)
            with self._lock:
                if ident in self._busy:
                    continue
                self._busy.add(ident)
            threading.Thread(target=self._work, args=(ident,), daemon=True).start()

    def _work(self, ident):
        from ..capture import window
        result = None
        try:
            surface = window(self.bus, ident)
            result = _shrink(surface)
        except Exception as error:
            self.failures[ident] = type(error).__name__
        finally:
            with self._lock:
                self._busy.discard(ident)

        def deliver():
            if result:
                data, w, h, stride = result
                try:
                    self.cache[ident] = (texture_from(data, w, h, stride), w / h, time.monotonic())
                    self.failures.pop(ident, None)
                except Exception as error:
                    self.failures[ident] = type(error).__name__
                if self.on_update:
                    self.on_update(ident)
            return False
        GLib.idle_add(deliver)

    def forget(self, live_ids):
        live = {str(i) for i in live_ids}
        for ident in list(self.cache):
            if ident not in live:
                del self.cache[ident]
