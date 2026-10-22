"""Window list and window control for the shell, through a small KWin script (the bridge).

KWin pushes the window list to us over D-Bus (org.makos.Windows.Report). Commands are one-shot KWin scripts,
generated from fixed templates; only window ids, numbers and short strings are interpolated, and strings are
JSON-encoded, so no caller-controlled text is ever executed as code.
"""
import json
import os
import re
import tempfile
import threading
from pathlib import Path

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib, GObject  # noqa: E402

from . import common

INTROSPECTION = '''<node><interface name="org.makos.Windows">
  <method name="Report"><arg type="s" name="json" direction="in"/></method>
</interface></node>'''

ID = re.compile(r'^\{?[0-9a-fA-F-]{8,40}\}?$')


class WindowBridge(GObject.Object):
    __gsignals__ = {'changed': (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, bus=None, bridge_js=None):
        super().__init__()
        self.bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION)
        self.state = {'windows': [], 'screens': [], 'desktops': [], 'current': 1}
        self.bridge_js = Path(bridge_js or common.SHARE / 'bridge/bridge.js')
        self._regid = None
        self._tmp = Path(tempfile.mkdtemp(prefix='makos-kwin-', dir=str(common.RUNTIME) if common.RUNTIME.exists() else None))

    # ----- D-Bus service side
    def export(self):
        info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        self._regid = self.bus.register_object('/Windows', info.interfaces[0], self._on_call, None, None)

    def _on_call(self, conn, sender, path, iface, method, params, invocation):
        if method == 'Report':
            try:
                self.state = json.loads(params.unpack()[0])
            except ValueError:
                pass
            self._schedule_changed()
        invocation.return_value(None)

    def _schedule_changed(self):
        """Coalesce bursts of updates (apps that retitle themselves constantly) into one 'changed' signal."""
        if getattr(self, '_changed_pending', False):
            return
        self._changed_pending = True

        def fire():
            self._changed_pending = False
            self.emit('changed')
            return False
        GLib.timeout_add(120, fire)

    # ----- loading the bridge script
    def load(self):
        def run():
            try:
                self._kwin('unloadScript', GLib.Variant('(s)', ('makos-bridge',)))
                self._kwin('loadScript', GLib.Variant('(ss)', (str(self.bridge_js), 'makos-bridge')))
                self._kwin('start', None)
            except GLib.Error as error:
                print('window bridge not loaded:', error.message, flush=True)
        threading.Thread(target=run, daemon=True).start()

    def _kwin(self, method, params, path='/Scripting', iface='org.kde.kwin.Scripting'):
        return self.bus.call_sync('org.kde.KWin', path, iface, method, params, None, Gio.DBusCallFlags.NONE, 3000, None)

    # ----- queries
    @property
    def windows(self):
        return self.state.get('windows', [])

    def app_windows(self):
        return [w for w in self.windows if w.get('normal') and not w.get('skip')]

    def windows_for(self, desktop_id):
        from .shell import apps
        keys = apps.identity(apps.lookup(desktop_id or '')) | {(desktop_id or '').removesuffix('.desktop').lower()}
        keys.discard('')
        out = []
        for w in self.app_windows():
            names = {str(w.get('desktopFile', '')).removesuffix('.desktop').lower(), str(w.get('cls', '')).lower()}
            names.discard('')
            if keys & names:
                out.append(w)
        return out

    # ----- commands
    def _run_script(self, body):
        def go():
            path = self._tmp / f'cmd-{os.getpid()}-{threading.get_ident()}-{GLib.get_monotonic_time()}.js'
            path.write_text(body)
            name = path.stem
            try:
                sid = self._kwin('loadScript', GLib.Variant('(ss)', (str(path), name))).unpack()[0]
                self._kwin('run', None, f'/Scripting/Script{sid}', 'org.kde.kwin.Script')
                self._kwin('unloadScript', GLib.Variant('(s)', (name,)))
            except GLib.Error as error:
                print('window command failed:', error.message, flush=True)
            finally:
                path.unlink(missing_ok=True)
        threading.Thread(target=go, daemon=True).start()

    @staticmethod
    def _find(win_id):
        if not ID.match(str(win_id)):
            raise ValueError('invalid window id')
        return ('var W = workspace.windowList().filter(function (x) { return String(x.internalId) === %s; })[0];'
                'if (!W) { print("makos: no such window"); } else {' % json.dumps(str(win_id)))

    def command(self, action, win_id, **kw):
        head = self._find(win_id)
        tail = '}'
        if action == 'activate':
            body = 'W.minimized = false; workspace.activeWindow = W;'
        elif action == 'close':
            body = 'W.closeWindow();'
        elif action == 'minimize':
            body = 'W.minimized = true;'
        elif action == 'maximize':
            body = 'W.setMaximize(true, true);'
        elif action == 'restore':
            body = 'W.setMaximize(false, false); W.minimized = false; W.fullScreen = false;'
        elif action == 'fullscreen':
            body = 'W.fullScreen = %s;' % ('true' if kw.get('on', True) else 'false')
        elif action == 'move_resize':
            vals = {k: int(kw[k]) for k in ('x', 'y', 'w', 'h') if k in kw}
            body = ('var g = W.frameGeometry; var n = {x: %d, y: %d, width: %d, height: %d}; W.frameGeometry = n;'
                    % (vals.get('x', 0), vals.get('y', 0), vals.get('w', 800), vals.get('h', 600)))
            if 'x' not in vals or 'y' not in vals or 'w' not in vals or 'h' not in vals:
                body = ('var g = W.frameGeometry; W.frameGeometry = {x: %s, y: %s, width: %s, height: %s};'
                        % tuple(str(vals[k]) if k in vals else 'g.' + n for k, n in (('x', 'x'), ('y', 'y'), ('w', 'width'), ('h', 'height'))))
        elif action == 'tile':
            side = kw.get('side', 'left')
            if side not in ('left', 'right', 'top', 'bottom'):
                raise ValueError('invalid tile side')
            body = ('var a = workspace.clientArea(KWin.MaximizeArea, W); var s = %s; var h = {x: a.x, y: a.y, width: a.width, height: a.height};'
                    'if (s === "left") h.width = a.width / 2; if (s === "right") { h.x = a.x + a.width / 2; h.width = a.width / 2; }'
                    'if (s === "top") h.height = a.height / 2; if (s === "bottom") { h.y = a.y + a.height / 2; h.height = a.height / 2; }'
                    'W.setMaximize(false, false); W.frameGeometry = h;' % json.dumps(side))
        elif action == 'to_desktop':
            n = int(kw['desktop'])
            body = 'var d = workspace.desktops.filter(function (x) { return x.x11DesktopNumber === %d; })[0]; if (d) W.desktops = [d];' % n
        else:
            raise ValueError('unknown window action')
        self._run_script(head + body + tail)

    def release(self, classes):
        """Give windows of these (lower-case) classes their title bar back: undoes the borderless home rule. Only `noBorder`
        is touched; the window keeps its size."""
        names = [str(c).lower() for c in classes if isinstance(c, str)]
        if not names:
            return
        self._run_script('var N = %s; workspace.windowList().forEach(function (w) {'
                         'var c = String(w.resourceClass).toLowerCase(), d = String(w.desktopFileName).toLowerCase().replace(/[.]desktop$/, "");'
                         'if (w.normalWindow && (N.indexOf(c) >= 0 || N.indexOf(d) >= 0) && w.noBorder) w.noBorder = false; });' % json.dumps(names))

    def switch_desktop(self, number):
        n = int(number)
        self._run_script('var d = workspace.desktops.filter(function (x) { return x.x11DesktopNumber === %d; })[0]; if (d) workspace.currentDesktop = d;' % n)
