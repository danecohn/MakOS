"""Shared context handed to every pane's build(ctx)."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

from .. import common, ui
from . import widgets


class Ctx:
    def __init__(self, app, window, status):
        self.app = app
        self.window = window
        self.status = status
        self._timer = 0

    @property
    def data(self):
        return common.load_settings()

    # ---- feedback
    def flash(self, text, error=False):
        self.status.set_text(text)
        (self.status.add_css_class if error else self.status.remove_css_class)('error')
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add_seconds(8, self._clear)

    def _clear(self):
        self._timer = 0
        self.status.set_text('')
        return False

    # ---- applying changes
    def do(self, fn, *args, ok=None, done=None, quick=False, **kwargs):
        """Run a backend call off the GTK thread. `ok` is the success message (str or callable(result)); failures show the
        error text. Shell-visible settings go through changed() so the running shell re-reads settings.json."""
        def work():
            return fn(*args, **kwargs)

        def after(result):
            bad = (isinstance(result, dict) and result.get('ok') is False) or result is False
            if bad:
                cancelled = isinstance(result, dict) and result.get('cancelled')
                self.flash('Cancelled.' if cancelled else ((result.get('error') if isinstance(result, dict) else '') or 'The system did not accept that change.'), True)
            else:
                if ok:
                    self.flash(ok(result) if callable(ok) else ok)
            self.changed()
            if done:
                done(result)

        def fail(error):
            self.flash(str(error) or error.__class__.__name__, True)
        widgets.run_async(work, after, fail)

    def changed(self):
        """Tell the running shell/apps that settings.json may have changed (launcher, wallpaper, fonts...)."""
        reload = getattr(self.app, 'reload_preferences', None)
        if reload:
            reload()
        ui.refresh_appearance()

    def saved(self, key, label=None):
        """Success message for a settings.json key, honest about whether the running shell acts on it yet."""
        from .registry import SHELL_HONORS
        text = label or 'Saved.'
        return text if SHELL_HONORS.get(key, True) else text + ' (Saved; the shell does not use this yet.)'

    def terminal(self, argv):
        from ..backends import sysutil
        return sysutil.popen(argv) is not None
