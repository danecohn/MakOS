"""Launcher Bar model: which items the bar shows and how windows map onto applications. Pure Python (no GTK).

Layout of the bar, left to right (top to bottom for side bars):
    pinned apps | running apps that are not pinned | separator | folder stacks | minimized windows | separator | Trash
"""
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .. import catalog

TRASH = 'trash-empty'
SHELL_CLASS = 'org.makos.shell'
# Window classes (lower case) of the real applications behind catalog entries. Internal apps are matched by id.
EXTRA_CLASSES = {
    'terminal': {'konsole', 'ptyxis', 'org.gnome.ptyxis', 'xterm', 'org.kde.konsole'},
    'paper': {'euro-office'}, 'digits': set(), 'slides': set(),
    'venture': {'amerikaventure', 'firefox', 'chromium', 'amerika-venture', 'org.mozilla.firefox'},
    'files': {'org.makos.files'},
}
FOLDERS = {  # id -> (name, icon, xdg key, default sub folder)
    'downloads': ('Downloads', 'folder-downloads', 'DOWNLOAD', 'Downloads'),
    'documents': ('Documents', 'folder-documents', 'DOCUMENTS', 'Documents'),
    'desktop': ('Desktop', 'folder-desktop', 'DESKTOP', 'Desktop'),
    'pictures': ('Pictures', 'folder-pictures', 'PICTURES', 'Pictures'),
    'music': ('Music', 'folder-music', 'MUSIC', 'Music'),
}
DEFAULT_FOLDERS = ['downloads', 'documents']
SEPARATOR_LENGTH = 12.0


@dataclass
class Item:
    kind: str                      # app | folder | window | trash | separator
    key: str                       # catalog id / folder id / window id / group key
    name: str = ''
    icon: str = ''                 # icon name in the MakOS theme
    pinned: bool = False
    running: bool = False
    windows: list = field(default_factory=list)   # window dicts belonging to this app (most recent first)
    badge: int = 0
    path: str = ''                 # folders
    app_id: str = ''               # window items: the catalog id of the owning app, if any

    def can_reorder(self):
        return self.kind == 'app' and self.pinned


# ------------------------------------------------------------------------------------------ window <-> app
def _keys_for(app):
    keys = {app.id, 'makos-' + app.id, 'org.makos.apps.' + app.id.replace('-', '_')}
    keys |= EXTRA_CLASSES.get(app.id, set())
    for command in app.command:
        try:
            exe = os.path.basename(shlex.split(command)[0]).lower()
        except (ValueError, IndexError):
            continue
        if app.id not in ('paper', 'digits', 'slides') and exe:
            keys.add(exe)
    return keys


_APP_KEYS = {a.id: _keys_for(a) for a in catalog.APPS}
_NAME_TO_ID = {a.name.lower(): a.id for a in catalog.APPS if a.internal}


def window_names(w):
    names = {str(w.get('desktopFile', '')).removesuffix('.desktop').lower(), str(w.get('cls', '')).lower()}
    names.discard('')
    return names


def app_id_for_window(w):
    """Catalog id of the application a window belongs to, or None for foreign applications."""
    names = window_names(w)
    if SHELL_CLASS in names:
        title = str(w.get('caption', '')).split(' — ')[0].split(' - ')[0].strip().lower()
        return _NAME_TO_ID.get(title)
    for app_id, keys in _APP_KEYS.items():
        if keys & names:
            return app_id
    return None


def group_key(w):
    """Stable key of the application a window belongs to: catalog id, else its class/desktop file name."""
    app_id = app_id_for_window(w)
    if app_id:
        return app_id
    names = sorted(window_names(w))
    return 'x:' + (names[0] if names else str(w.get('id', '')))


def display_name(w):
    app_id = app_id_for_window(w)
    if app_id:
        return catalog.BY_ID[app_id].name
    cls = str(w.get('desktopFile') or w.get('cls') or 'Application')
    cls = cls.removesuffix('.desktop').rsplit('.', 1)[-1].replace('-', ' ').replace('_', ' ')
    return cls[:1].upper() + cls[1:]


def windows_by_group(windows):
    """{group key: [windows most recent first]}"""
    groups = {}
    for w in sorted(windows, key=lambda x: -int(x.get('mru', 0))):
        groups.setdefault(group_key(w), []).append(w)
    return groups


# ------------------------------------------------------------------------------------------ folders
def folder_path(folder_id, home=None, env=None):
    """Path of a stack folder. Honours ~/.config/user-dirs.dirs."""
    home = Path(home or Path.home())
    name = FOLDERS[folder_id][3]
    key = FOLDERS[folder_id][2]
    try:
        cfg = Path((env or os.environ).get('XDG_CONFIG_HOME') or home / '.config') / 'user-dirs.dirs'
        for line in cfg.read_text().splitlines():
            if line.startswith(f'XDG_{key}_DIR='):
                value = shlex.split(line.split('=', 1)[1])[0].replace('$HOME', str(home))
                if value.startswith('/'):
                    return Path(value)
    except (OSError, ValueError, IndexError):
        pass
    return home / name


def list_folder(path, limit=40):
    """Visible entries of a folder, newest first. Symlink targets are not followed. Never raises."""
    out = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith('.') or entry.name.endswith('~'):
                    continue
                try:
                    out.append((entry.stat(follow_symlinks=False).st_mtime, entry.name, entry.is_dir(follow_symlinks=False)))
                except OSError:
                    continue
    except OSError:
        return []
    out.sort(key=lambda e: (-e[0], e[1].lower()))
    return [(name, is_dir) for _, name, is_dir in out[:limit]]


# ------------------------------------------------------------------------------------------ items
def clean_pins(pins):
    seen, out = set(), []
    for p in pins:
        if isinstance(p, str) and p not in seen and (p in catalog.BY_ID):
            seen.add(p)
            out.append(p)
    return out


def _badge(badges, key):
    """Badge count for an item key; unknown applications ('x:class') are looked up by their bare class name."""
    return int(badges.get(key) or badges.get(key.removeprefix('x:')) or 0)


def build_items(prefs, windows, badges=None, show_recents=False):
    """The ordered Item list for the bar from preferences, the window list and badge counts."""
    badges = badges or {}
    pins = [p for p in clean_pins(prefs.get('pins', [])) if p != TRASH]
    groups = windows_by_group([w for w in windows if w.get('normal', True) and not w.get('skip')])
    items = []
    used = set()
    for app_id in pins:
        rec = catalog.BY_ID[app_id]
        wins = groups.get(app_id, [])
        used.add(app_id)
        items.append(Item('app', app_id, rec.name, rec.icon, pinned=True, running=bool(wins), windows=wins,
                          badge=_badge(badges, app_id)))
    extra = [(k, v) for k, v in groups.items() if k not in used]
    # running, unpinned applications keep a stable order: by their oldest window id
    extra.sort(key=lambda kv: min(str(w.get('id')) for w in kv[1]))
    for key, wins in extra:
        if key in used:
            continue
        used.add(key)
        rec = catalog.BY_ID.get(key)
        items.append(Item('app', key, rec.name if rec else display_name(wins[0]), rec.icon if rec else '', pinned=False,
                          running=True, windows=wins, badge=_badge(badges, key), app_id=rec.id if rec else ''))
    folders = [f for f in prefs.get('launcher_folders', DEFAULT_FOLDERS) if f in FOLDERS]
    items.append(Item('separator', 'sep-folders'))
    for fid in folders:
        name, icon, _, _ = FOLDERS[fid]
        items.append(Item('folder', fid, name, icon, pinned=True, path=str(folder_path(fid))))
    minimized = sorted((w for w in windows if w.get('minimized') and w.get('normal', True) and not w.get('skip')),
                       key=lambda w: int(w.get('minimizedAt', w.get('mru', 0))))
    for w in minimized:
        gid = app_id_for_window(w) or ''
        rec = catalog.BY_ID.get(gid)
        items.append(Item('window', str(w['id']), str(w.get('caption', ''))[:60], rec.icon if rec else '', windows=[w], app_id=gid))
    items.append(Item('separator', 'sep-trash'))
    rec = catalog.BY_ID[TRASH]
    items.append(Item('trash', TRASH, rec.name, rec.icon, pinned=True))
    return items


def item_lengths(items, base):
    return [SEPARATOR_LENGTH if i.kind == 'separator' else float(base) for i in items]


def item_magnifiable(items):
    return [i.kind != 'separator' for i in items]


def reorder_range(items):
    """Inclusive index range of the pinned app items (the only ones that can be dragged to reorder), or None."""
    idx = [n for n, i in enumerate(items) if i.can_reorder()]
    return (idx[0], idx[-1]) if idx else None


# ------------------------------------------------------------------------------------------ pin editing
def pin(pins, app_id, index=None):
    pins = [p for p in clean_pins(pins) if p != app_id]
    if app_id not in catalog.BY_ID:
        return pins
    # keep Trash last in the stored list so older settings stay valid
    trash = TRASH in pins
    pins = [p for p in pins if p != TRASH]
    pins.insert(len(pins) if index is None else max(0, min(index, len(pins))), app_id)
    return pins + ([TRASH] if trash and app_id != TRASH else [])


def unpin(pins, app_id):
    return [p for p in clean_pins(pins) if p != app_id]


def reorder(pins, app_id, new_index):
    """Move pinned app `app_id` to position `new_index` among the pinned apps (Trash excluded)."""
    apps = [p for p in clean_pins(pins) if p != TRASH]
    if app_id not in apps:
        return list(pins)
    apps.remove(app_id)
    apps.insert(max(0, min(new_index, len(apps))), app_id)
    return apps + ([TRASH] if TRASH in pins else [])


# ------------------------------------------------------------------------------------------ menus
def context_actions(item, running_windows=0):
    """Right-click menu entries as (key, label) for an item; ('-', '') is a separator."""
    out = []
    if item.kind == 'app':
        out.append(('open', 'Open'))
        if running_windows:
            out.append(('-', ''))
        out.append(('-', ''))
        out.append(('remove' if item.pinned else 'keep', 'Remove from Launcher Bar' if item.pinned else 'Keep in Launcher Bar'))
        out.append(('show', 'Show in Files'))
        if item.running:
            out.append(('hide', 'Hide'))
            out.append(('quit', 'Quit'))
    elif item.kind == 'folder':
        out += [('open', 'Open in Files'), ('-', ''), ('sort', 'Sort by Date Added'), ('view-fan', 'View as Fan'),
                ('view-grid', 'View as Grid'), ('view-auto', 'View Automatically'), ('-', ''),
                ('remove-folder', 'Remove from Launcher Bar')]
    elif item.kind == 'window':
        out += [('restore', 'Restore'), ('close', 'Close')]
    elif item.kind == 'trash':
        out += [('open', 'Open Trash')]
    return out


def badge_text(count):
    count = int(count)
    if count <= 0:
        return ''
    return '99+' if count > 99 else str(count)


# ------------------------------------------------------------------------------------------ stack contents
_ICONS = {
    'file-image': ('png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'tif', 'tiff', 'heic'),
    'file-pdf': ('pdf',), 'file-text': ('txt', 'md', 'log', 'rtf', 'csv'),
    'file-audio': ('mp3', 'wav', 'flac', 'ogg', 'm4a', 'opus'), 'file-video': ('mp4', 'mkv', 'mov', 'webm', 'avi'),
    'file-archive': ('zip', 'tar', 'gz', 'xz', 'bz2', '7z', 'deb', 'rar'),
    'file-code': ('py', 'js', 'c', 'h', 'rs', 'go', 'sh', 'json', 'html', 'css', 'cpp', 'java', 'ts'),
    'file-document': ('doc', 'docx', 'odt'), 'file-spreadsheet': ('xls', 'xlsx', 'ods'),
    'file-presentation': ('ppt', 'pptx', 'odp'),
}
_EXT_ICON = {ext: icon for icon, exts in _ICONS.items() for ext in exts}


def file_icon(name, is_dir=False):
    """Icon name (MakOS theme) for a file shown inside a stack."""
    if is_dir:
        return 'folder'
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return _EXT_ICON.get(ext, 'file-generic')
