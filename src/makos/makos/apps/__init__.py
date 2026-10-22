"""MakkOS applications. One module per app; each exposes open_window(app, path=None).

Apps in SEPARATE run in their own `makos-app` process when started by the shell (crash isolation,
no heavy libraries inside the shell, and a per-process global menu). Files and Settings also run separately; the private integration rig can explicitly embed them.
"""
import importlib
import os
import shutil
import subprocess
import threading
import sys
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib
from .. import ui, catalog, common

MODULES = {'calculator': 'calculator', 'text-editor': 'texteditor', 'notes': 'notes', 'calendar': 'calendar', 'activity': 'activity',
           'disk-utility': 'diskutil', 'system-info': 'sysinfo', 'screenshot': 'screenshot', 'software-center': 'softwarecenter',
           'preview': 'preview', 'pictures': 'pictures', 'tunes': 'tunes', 'movies': 'movies'}
SEPARATE = frozenset(MODULES)
EXTERNAL = ('chatgpt', 'claude', 'paper', 'digits', 'slides', 'makbox', 'venture', 'terminal', 'render', 'engine', 'sprite', 'studio')
SINGLE_INSTANCE = frozenset({'tunes'})


def makos_app_path():
    local = common.SOURCE / 'bin/makos-app'
    return str(local) if local.exists() else (shutil.which('makos-app') or 'makos-app')


def child_env():
    env = dict(os.environ)
    env.pop('LD_PRELOAD', None)  # the layer-shell preload belongs to the shell executable only
    return env


def spawn(app_id, path=None):
    argv = [makos_app_path(), app_id] + ([str(path)] if path else [])
    proc = subprocess.Popen(argv, env=child_env(), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=proc.wait, daemon=True).start()
    return proc


def which_local(exe):
    """PATH lookup that also finds MakkOS helper scripts in a source checkout (bin/)."""
    found = shutil.which(exe)
    if found:
        return found
    local = common.SOURCE / 'bin' / exe
    return str(local) if exe.startswith('makos-') and local.exists() else None


def call_shell(name):
    """Ask the running shell to perform a control action (overlays such as Widgets live in the shell)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync('org.makos.Shell', '/Control', 'org.makos.Control', 'Action', GLib.Variant('(s)', (name,)), None, Gio.DBusCallFlags.NONE, 3000, None)
        return True
    except GLib.Error:
        return False


def launch_external(app, record, path=None):
    if record.id == 'terminal':
        from .terminal import argv_for
        argv = argv_for(which_local, path)
    else:
        argv = catalog.resolve(record, which_local)
        if argv:
            argv[0] = which_local(argv[0]) or argv[0]
        if argv and path:
            argv.append(str(path))
    if not argv:
        ui.message(app, record.name, 'The application backend is not installed.')
        return
    proc = subprocess.Popen(argv, env=child_env(), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=proc.wait, daemon=True).start()


def launch(app, app_id, path=None):
    if app_id in ('files', 'settings') and not isinstance(app, Applications) and os.environ.get('MAKOS_RIG_EMBED_APPS') != '1':
        return spawn(app_id, path)
    if app_id == 'files':
        from ..files import Files
        return Files(app, path)
    if app_id == 'settings':
        from ..settings import Settings
        return Settings(app)
    if app_id in ('seek', 'spread', 'desktops', 'widgets'):
        if hasattr(app, 'action'):
            return app.action(app_id)
        return call_shell(app_id)  # started as its own process (desktop entry): forward to the shell
    if app_id in EXTERNAL:
        return launch_external(app, catalog.BY_ID[app_id], path)
    if app_id == 'trash-empty':
        context = Gio.AppLaunchContext()
        context.unsetenv('LD_PRELOAD')
        try:
            Gio.AppInfo.launch_default_for_uri('trash:///', context)
        except GLib.Error:
            ui.message(app, 'Trash', 'No system trash handler is installed. Files have not been changed.')
        return
    if app_id in MODULES:
        if app_id in SEPARATE and not isinstance(app, Applications):
            return spawn(app_id, path)
        module = importlib.import_module('.' + MODULES[app_id], __name__)
        return module.open_window(app, path)
    record = catalog.BY_ID.get(app_id)
    ui.message(app, record.name if record else 'MakkOS', 'This application is not implemented in this development build.')


class Applications(Gtk.Application):
    """Standalone process for one MakkOS app (makos-app <id> [files...])."""

    def __init__(self, app_id, path=None):
        flags = Gio.ApplicationFlags.HANDLES_OPEN | (Gio.ApplicationFlags.DEFAULT_FLAGS if app_id in SINGLE_INSTANCE else Gio.ApplicationFlags.NON_UNIQUE)
        super().__init__(application_id='org.makos.Apps.' + app_id.replace('-', '_'), flags=flags)
        self.app_id = app_id
        self.path = path
        self.standalone = True
        self._themed = False
        quit_ms = os.environ.get('MAKOS_APP_QUIT_MS')  # rig only: lets a test close a window-less run
        if quit_ms and quit_ms.isdigit():
            GLib.timeout_add(int(quit_ms), lambda: (self.quit(), False)[1])

    def theme(self):
        if not self._themed:
            self._theme = ui.install_theme()
            self._themed = True

    def do_activate(self):
        self.theme()
        launch(self, self.app_id, self.path)

    def do_open(self, files, _n, _hint):
        self.theme()
        for f in files:
            launch(self, self.app_id, f.get_path() or f.get_uri())
