"""Launcher badge counts: one small API, no GTK.

Producers: the notification server (unread banners per app), apps/other code (``set``/``add``),
and the de-facto ``com.canonical.Unity.LauncherEntry`` D-Bus signal that Electron apps,
Firefox, Chromium, Telegram, Thunderbird and others already emit (``attach``).
Consumer (launcher): ``badges.default.get(app_id)``, ``.counts()`` (suitable for
``launcher.build_items(..., badges=counts)``), ``.text(app_id)`` ('' / '7' / '99+'),
``.progress(app_id)`` (None or 0..1) and ``.connect(callback)`` where
``callback(app_id, count, progress)`` runs on the GLib main loop. GPL-3.0-only.
"""
import re

MAX_SHOWN = 99


def app_id_from_desktop(desktop_id, known=()):
    """Map a desktop-file id ('org.mozilla.firefox.desktop', 'makos-files', 'application://x.desktop')
    to a launcher id. Known catalog ids win (so 'makos-files.desktop' -> 'files')."""
    if not desktop_id:
        return ''
    name = str(desktop_id).strip()
    if name.startswith('application://'):
        name = name[len('application://'):]
    name = re.sub(r'\.desktop$', '', name)
    name = name.rsplit('/', 1)[-1].lower()
    if name.startswith('makos-'):
        name = name[len('makos-'):]
    known = tuple(known)
    if name in known:
        return name
    last = name.rsplit('.', 1)[-1]
    if last in known:
        return last
    return name


class Badges:
    def __init__(self):
        self._counts = {}
        self._progress = {}
        self._callbacks = []
        self._subscription = None
        self._conn = None

    # ---- consumer API
    def get(self, app_id):
        return self._counts.get(app_id, 0)

    def counts(self):
        return {k: v for k, v in self._counts.items() if v > 0}

    def total(self):
        return sum(self._counts.values())

    def text(self, app_id):
        n = self.get(app_id)
        return '' if n <= 0 else (str(n) if n <= MAX_SHOWN else '%d+' % MAX_SHOWN)

    def progress(self, app_id):
        return self._progress.get(app_id)

    def connect(self, callback):
        self._callbacks.append(callback)
        return callback

    def disconnect(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    # ---- producer API
    def set(self, app_id, count=None, progress='keep'):
        if not app_id:
            return
        changed = False
        if count is not None:
            count = max(0, min(int(count), 9999))
            if self._counts.get(app_id, 0) != count:
                self._counts[app_id] = count
                changed = True
            if count == 0:
                self._counts.pop(app_id, None)
        if progress != 'keep':
            progress = None if progress is None else max(0.0, min(1.0, float(progress)))
            if self._progress.get(app_id) != progress:
                changed = True
                if progress is None:
                    self._progress.pop(app_id, None)
                else:
                    self._progress[app_id] = progress
        if changed:
            self._emit(app_id)

    def add(self, app_id, amount=1):
        self.set(app_id, self.get(app_id) + amount)

    def clear(self, app_id):
        self.set(app_id, 0, None)

    def _emit(self, app_id):
        for callback in list(self._callbacks):
            try:
                callback(app_id, self.get(app_id), self.progress(app_id))
            except Exception:  # a broken consumer must not stop producers
                pass

    # ---- Unity LauncherEntry
    def apply_launcher_entry(self, app_uri, props, known=()):
        """props is the unpacked a{sv} from com.canonical.Unity.LauncherEntry.Update."""
        app_id = app_id_from_desktop(app_uri, known)
        if not app_id:
            return
        count = None
        if 'count' in props or 'count-visible' in props:
            visible = bool(props.get('count-visible', True))
            count = int(props.get('count', 0)) if visible else 0
        progress = 'keep'
        if 'progress-visible' in props or 'progress' in props:
            progress = float(props.get('progress', 0)) if props.get('progress-visible', True) else None
        self.set(app_id, count, progress)

    def attach(self, conn, known=()):
        """Subscribe to Unity LauncherEntry updates on a Gio.DBusConnection."""
        from gi.repository import Gio

        def update(_c, _sender, _path, _iface, _signal, params):
            try:
                uri, props = params.unpack()
            except (ValueError, TypeError):
                return
            if isinstance(uri, str) and isinstance(props, dict):
                self.apply_launcher_entry(uri, props, known)
        self.detach()
        self._conn = conn
        self._subscription = conn.signal_subscribe(None, 'com.canonical.Unity.LauncherEntry', 'Update', None, None,
                                                   Gio.DBusSignalFlags.NONE, update)

    def detach(self):
        if self._conn is not None and self._subscription is not None:
            self._conn.signal_unsubscribe(self._subscription)
        self._conn = self._subscription = None


default = Badges()
