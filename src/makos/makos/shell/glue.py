"""Launcher-and-windows services attached to the Shell: Launcher Bar, desktop layer, Spread, Desks, app switcher,
hot-corner dispatch, full screen behaviour and window memory.

main.py owns the Shell application; this object keeps everything of this area in one place so the Shell only needs a few
one-line hooks (`self.services = Services(self)`, `services.windows_changed()`, `services.action(name)`,
`services.apply_preferences()`). Unknown attributes fall through to the Shell, so the pieces written against "the shell"
(Dock, Spread, ...) can use `host.bridge`, `host.surface(...)` and friends directly.
"""
import json
import os
import time
from pathlib import Path

from gi.repository import Gio, GLib

from .. import badges as badge_mod
from .. import common
from . import geometry, layer
from . import launcher as lm
from .desktop import DesktopLayer
from .thumbs import Thumbs


class Services:
    def __init__(self, shell):
        self._shell = shell
        self.thumbs = Thumbs(shell.bus, on_update=self._thumb_ready)
        self.dock = None
        self.desktop_layer = None
        self.genie = None
        self.spread_view = None
        self.switcher = None
        self.memory = geometry.clean_memory(self._read_json(common.STATE / 'window-memory.json'))
        self._last_active = None
        self._fullscreen = False
        self._watch_settings()

    def __getattr__(self, name):
        return getattr(self._shell, name)

    def _watch_settings(self):
        """Settings changes apply live: any write of settings.json (the Settings window, a script, a hand edit) reloads."""
        try:
            common.CONFIG.mkdir(parents=True, exist_ok=True)
            self._monitor = Gio.File.new_for_path(str(common.CONFIG)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error as error:
            print('settings watch unavailable:', error.message, flush=True)
            return
        self._reload_timer = 0

        def changed(_m, file, other, event):
            names = {file.get_basename() if file else '', other.get_basename() if other else ''}
            if 'settings.json' not in names or event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                                                             Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.RENAMED):
                return
            if self._reload_timer:
                GLib.source_remove(self._reload_timer)

            def reload():
                self._reload_timer = 0
                self._shell.reload_preferences()
                return False
            self._reload_timer = GLib.timeout_add(150, reload)
        self._monitor.connect('changed', changed)

    # ------------------------------------------------------------------------------------------ small helpers
    @staticmethod
    def _read_json(path):
        try:
            return json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return {}

    def launch_with(self, app_id, path):
        from ..apps import launch
        return launch(self._shell, app_id, path)

    def open_path(self, path):
        p = Path(path)
        if p.is_dir():
            return self.launch_with('files', str(p))
        return self._shell.open_file(p)

    # ------------------------------------------------------------------------------------------ desktop layer
    def build_desktop(self):
        shell = self._shell
        shell.desktop = shell.surface('Desktop', 'background', ('top', 'bottom', 'left', 'right'))
        layer.LS.set_exclusive_zone(shell.desktop, -1)  # extend under the menu bar and Launcher Bar instead of avoiding them
        self.desktop_layer = DesktopLayer(shell.desktop, shell.preferences)
        shell.desktop.present()
        return shell.desktop

    # ------------------------------------------------------------------------------------------ launcher bar
    def build_launcher(self):
        from .dock import Dock
        if self.dock is None:
            self.dock = Dock(self)
            badge_mod.default.connect(lambda *_: self.dock.set_badges(badge_mod.default.counts()))
            self.dock.set_badges(badge_mod.default.counts())
        self._shell.launcher = self.dock.window
        self.dock.set_windows(self.bridge.app_windows())
        return self.dock.window

    def apply_preferences(self):
        shell = self._shell
        if self.desktop_layer:
            self.desktop_layer.update(shell.preferences)
        if self.dock:
            self.dock.apply_preferences(shell.preferences)

    # ------------------------------------------------------------------------------------------ window state
    def windows_changed(self):
        state = self.bridge.state
        wins = self.bridge.app_windows()
        if self.dock:
            self.dock.set_windows(wins)
        active = next((w for w in wins if w.get('active')), None)
        if active and active.get('id') != self._last_active:
            prev = self._last_active
            self._last_active = active.get('id')
            gid = lm.app_id_for_window(active)
            if gid:
                badge_mod.default.clear(gid)
            if prev:
                self.thumbs.request([prev])
        full = bool(active and active.get('fullscreen'))
        if full != self._fullscreen:
            self._fullscreen = full
            if self.dock:
                self.dock.set_fullscreen(full)
        self._persist_memory(state.get('memory'))
        self.thumbs.forget([w['id'] for w in wins])

    def _thumb_ready(self, ident):
        if self.dock:
            self.dock.view.queue_draw()
        for view in (self.spread_view,):
            if view is not None:
                view.thumb_ready(ident)

    def _persist_memory(self, memory):
        if not isinstance(memory, dict):
            return
        clean = geometry.clean_memory(memory)
        if clean == self.memory:
            return
        self.memory = clean
        try:
            common.STATE.mkdir(parents=True, exist_ok=True)
            tmp = common.STATE / 'window-memory.json.tmp'
            tmp.write_text(json.dumps(clean, indent=1) + '\n')
            tmp.replace(common.STATE / 'window-memory.json')
        except OSError as error:
            print('window memory not saved:', error, flush=True)

    # ------------------------------------------------------------------------------------------ actions
    def action(self, name):
        """Handle launcher/window actions. Returns True when the action was consumed."""
        if name == 'launcher-reveal':
            if self.dock:
                self.dock.reveal()
            return True
        if name.startswith('rig:') and os.environ.get('MAKOS_RIG_SHOTS'):
            self._rig(name[4:])
            return True
        return False

    # ------------------------------------------------------------------------------------------ rig-only hooks
    def _rig(self, cmd):
        """Test hooks, active only when MAKOS_RIG_SHOTS is set (the private rig): compositor screenshots by name, the
        dock's layout as JSON, and frame-time recording."""
        out = Path(os.environ['MAKOS_RIG_SHOTS'])
        if cmd.startswith('shot:'):
            from ..capture import workspace
            name = cmd[5:]

            def take():
                tmp = out / (name + '.tmp.png')
                workspace(self.bus).write_to_png(str(tmp))
                os.replace(tmp, out / (name + '.png'))
            self._shell.background(take, lambda _r: print('RIG_SHOT ' + name, flush=True))
        elif cmd == 'dockstate' and self.dock:
            d = self.dock
            placed = d.displayed()
            data = {'pos': d.pos, 'style': d.style, 'base': d.base, 'zoom': d.zoom, 'strength': d.strength, 'surface': d.surface_size(),
                    'pointer': d.pointer, 'p_s': d.p_s, 'visible': d.autohide.visible, 'slide': d.slide, 'fullscreen': d.fullscreen, 'popover': d.popover is not None,
                    'pins': self._shell.preferences.get('pins'), 'exclusive': None,
                    'items': [{'kind': it.kind, 'key': it.key, 'name': it.name, 'running': it.running, 'badge': it.badge,
                               'start': p.start, 'length': p.length, 'rect': list(d.item_rect(i, placed)) if it.kind != 'separator' else None}
                              for i, (it, p) in enumerate(zip(d.items, placed))]}
            tmp = out / 'dockstate.tmp'
            tmp.write_text(json.dumps(data, indent=1))
            os.replace(tmp, out / 'dockstate.json')
        elif cmd == 'frames:start' and self.dock:
            self.dock.frame_deltas = []
            self.dock.record_frames = True
        elif cmd == 'frames:stop' and self.dock:
            self.dock.record_frames = False
            deltas = sorted(self.dock.frame_deltas)
            data = {'frames': len(deltas), 'median_ms': deltas[len(deltas) // 2] if deltas else None,
                    'p95_ms': deltas[int(len(deltas) * .95)] if deltas else None, 'max_ms': deltas[-1] if deltas else None}
            (out / 'frames.json').write_text(json.dumps(data, indent=1))
