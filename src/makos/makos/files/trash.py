"""FreeDesktop.org Trash specification reader: list, restore and empty without needing gvfs.

Moving items *to* the trash is done with Gio.File.trash() (see ops.py); this module
finds them again so that Undo, Restore, the Trash view and Empty Trash all work, also
for per-mount trash directories (``/mnt/x/.Trash-1000``).
"""
import configparser
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote


@dataclass
class TrashItem:
    name: str            # name inside trash/files
    file: str            # absolute path of the trashed item
    info: str            # absolute path of the .trashinfo
    orig: str            # absolute original path
    deleted: float       # unix time
    trash_dir: str
    is_dir: bool = False
    size: int = 0


def data_home():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')


def mount_points():
    points = []
    try:
        with open('/proc/self/mountinfo') as stream:
            for line in stream:
                parts = line.split()
                if len(parts) > 8:
                    mp = parts[4].replace('\\040', ' ')
                    fstype = parts[parts.index('-') + 1] if '-' in parts else ''
                    if fstype not in ('proc', 'sysfs', 'devtmpfs', 'cgroup', 'cgroup2', 'tmpfs', 'devpts', 'securityfs',
                                      'pstore', 'bpf', 'debugfs', 'tracefs', 'configfs', 'fusectl', 'mqueue', 'hugetlbfs',
                                      'autofs', 'binfmt_misc', 'overlay', 'squashfs') or mp.startswith(('/media', '/mnt', '/run/media')):
                        points.append(mp)
    except OSError:
        pass
    return points


def trash_dirs(extra_topdirs=()):
    """Return [(trash_dir, topdir_or_None)] that exist. First entry is the home trash."""
    result = []
    home = data_home() / 'Trash'
    if home.is_dir():
        result.append((str(home), None))
    uid = os.getuid()
    for top in list(mount_points()) + list(extra_topdirs):
        shared = Path(top) / '.Trash'
        try:
            st = shared.lstat()
            if stat.S_ISDIR(st.st_mode) and st.st_mode & stat.S_ISVTX and not stat.S_ISLNK(st.st_mode):
                cand = shared / str(uid)
                if cand.is_dir():
                    result.append((str(cand), top))
        except OSError:
            pass
        own = Path(top) / f'.Trash-{uid}'
        try:
            if own.is_dir() and not own.is_symlink():
                result.append((str(own), top))
        except OSError:
            pass
    seen, out = set(), []
    for item in result:
        if item[0] not in seen:
            seen.add(item[0])
            out.append(item)
    return out


def read_info(info_path, topdir=None):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        with open(info_path, encoding='utf-8', errors='replace') as stream:
            cp.read_file(stream)
        raw = cp.get('Trash Info', 'Path')
        date = cp.get('Trash Info', 'DeletionDate', fallback='')
    except (OSError, configparser.Error):
        return None
    orig = unquote(raw)
    if topdir and not os.path.isabs(orig):
        orig = os.path.join(topdir, orig)
    try:
        ts = datetime.fromisoformat(date).timestamp()
    except ValueError:
        ts = 0.0
    return orig, ts


def list_trash(extra_topdirs=()):
    items = []
    for tdir, top in trash_dirs(extra_topdirs):
        files = Path(tdir) / 'files'
        try:
            names = list(os.scandir(files))
        except OSError:
            continue
        for child in names:
            info = Path(tdir) / 'info' / (child.name + '.trashinfo')
            parsed = read_info(info, top) if info.exists() else None
            orig, ts = parsed if parsed else ('', 0.0)
            try:
                st = child.stat(follow_symlinks=False)
                is_dir, size = stat.S_ISDIR(st.st_mode), st.st_size
                if not parsed:
                    ts = st.st_mtime
            except OSError:
                is_dir, size = False, 0
            items.append(TrashItem(child.name, child.path, str(info), orig, ts, tdir, is_dir, size))
    items.sort(key=lambda t: t.deleted, reverse=True)
    return items


def find_trashed(orig_path, since=0.0, extra_topdirs=()):
    """Most recently trashed item whose original path is ``orig_path``."""
    orig_path = os.path.abspath(orig_path)
    best = None
    for item in list_trash(extra_topdirs):
        if item.orig == orig_path and item.deleted >= since - 2:
            if best is None or item.deleted > best.deleted:
                best = item
    return best


def restore(item, target=None, parents=True):
    """Move a trashed item back. Raises FileExistsError if the destination exists."""
    target = os.fspath(target or item.orig)
    if not target:
        raise FileNotFoundError('The original location of this item is unknown.')
    if os.path.lexists(target):
        raise FileExistsError(target)
    folder = os.path.dirname(target)
    if parents and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    os.rename(item.file, target) if _same_device(item.file, folder) else _move_across(item.file, target)
    try:
        os.unlink(item.info)
    except OSError:
        pass
    return target


def _same_device(a, b):
    try:
        return os.lstat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _move_across(src, dst):
    import shutil
    shutil.move(src, dst)


def delete_item(item):
    from . import ops
    ops.delete_path(item.file)
    try:
        os.unlink(item.info)
    except OSError:
        pass


def empty(extra_topdirs=(), cancel=None):
    """Permanently delete everything in every trash. Returns (deleted, errors)."""
    done, errors = 0, []
    for item in list_trash(extra_topdirs):
        if cancel is not None and cancel.is_set():
            break
        try:
            delete_item(item)
            done += 1
        except Exception as exc:  # report and continue
            errors.append(f'{item.name}: {exc}')
    if cancel is None or not cancel.is_set():
        for tdir, _top in trash_dirs(extra_topdirs):
            try:
                for leftover in os.scandir(Path(tdir) / 'info'):
                    stem = leftover.name[:-len('.trashinfo')]
                    if leftover.name.endswith('.trashinfo') and not os.path.lexists(Path(tdir) / 'files' / stem):
                        os.unlink(leftover.path)  # orphan info with no file
            except OSError:
                pass
    return done, errors


def is_empty(extra_topdirs=()):
    for tdir, _top in trash_dirs(extra_topdirs):
        try:
            with os.scandir(Path(tdir) / 'files') as scan:
                if any(True for _ in scan):
                    return False
        except OSError:
            pass
    return True
