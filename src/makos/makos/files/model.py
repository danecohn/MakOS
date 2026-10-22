"""Pure file-listing model for Files: no GTK, safe to unit-test with temp directories.

Listings never follow symlinks for recursion and turn OS errors into human messages.
"""
import errno
import os
import re
import stat as statmod
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

try:  # Gio is only used for MIME descriptions; the module also works without it.
    from gi.repository import Gio
except Exception:  # pragma: no cover
    Gio = None

MAX_ENTRIES = 1_000_000          # hard safety bound for one folder listing
SORT_KEYS = ('name', 'modified', 'size', 'kind', 'created')


@dataclass
class Entry:
    name: str
    path: str                     # absolute local path, or '' for remote entries
    uri: str = ''
    is_dir: bool = False          # folder or symlink to a folder (navigable)
    is_symlink: bool = False
    broken_link: bool = False
    link_target: str = ''
    size: int = 0
    mtime: float = 0.0
    btime: float = 0.0
    mode: int = 0
    mime: str = ''
    kind: str = ''
    icon: str = 'file-generic'
    hidden: bool = False
    readable: bool = True
    where: str = ''               # parent folder shown in search/recents/trash views
    orig_path: str = ''           # trash: original location
    deleted: float = 0.0          # trash: deletion time
    extra: dict = field(default_factory=dict)

    @property
    def expandable(self):
        """Only real folders expand in list view: a symlink never recurses."""
        return self.is_dir and not self.is_symlink

    @property
    def location(self):
        return self.uri or self.path


class FolderError(Exception):
    """An error whose text is already suitable for the user."""


def human_error(exc, what=''):
    name = f'“{what}”' if what else 'this item'
    code = getattr(exc, 'errno', None)
    if isinstance(exc, PermissionError) or code in (errno.EACCES, errno.EPERM):
        return f'You do not have permission to access {name}.'
    if isinstance(exc, FileNotFoundError) or code == errno.ENOENT:
        return f'{name[0].upper() + name[1:]} no longer exists. If it is on a drive or server, it may have been disconnected.'
    if isinstance(exc, NotADirectoryError) or code == errno.ENOTDIR:
        return f'{name[0].upper() + name[1:]} is not a folder.'
    if isinstance(exc, FileExistsError) or code == errno.EEXIST:
        return f'An item named {name} already exists.'
    if code in (errno.ENOSPC, errno.EDQUOT):
        return 'There is not enough free space on the destination.'
    if code == errno.EROFS:
        return 'The destination is read-only.'
    if code in (errno.ENOTCONN, errno.ESTALE, errno.EIO, errno.ETIMEDOUT, errno.EHOSTDOWN, errno.ECONNRESET):
        return f'{name[0].upper() + name[1:]} is not responding. Check the connection and try again.'
    if code == errno.ELOOP:
        return f'{name[0].upper() + name[1:]} is part of a link loop and was not opened.'
    if code == errno.ENAMETOOLONG:
        return 'That name is too long.'
    if code == errno.EBUSY:
        return f'{name[0].upper() + name[1:]} is busy.'
    msg = getattr(exc, 'strerror', None) or getattr(exc, 'message', None) or str(exc)
    return f'{msg}'


_MIME_CACHE = {}
_DESC_CACHE = {}
SPECIAL_DIRS = {'Desktop': 'folder-desktop', 'Documents': 'folder-documents', 'Downloads': 'folder-downloads',
                'Music': 'folder-music', 'Pictures': 'folder-pictures', 'Videos': 'folder-movies',
                'Movies': 'folder-movies', 'Applications': 'folder-applications', 'Public': 'folder-network'}
EXTRA_MIME = {'.md': 'text/markdown', '.py': 'text/x-python', '.rs': 'text/rust', '.toml': 'application/toml',
              '.yml': 'application/yaml', '.yaml': 'application/yaml', '.ts': 'text/x-typescript',
              '.zst': 'application/zstd', '.7z': 'application/x-7z-compressed', '.deb': 'application/vnd.debian.binary-package'}


def content_type(name):
    ext = os.path.splitext(name)[1].lower()
    hit = _MIME_CACHE.get(ext or name)
    if hit:
        return hit
    mime = ''
    if Gio is not None:
        try:
            mime = Gio.content_type_guess(name, None)[0] or ''
        except Exception:
            mime = ''
    if mime in ('', 'application/octet-stream') and ext in EXTRA_MIME:
        mime = EXTRA_MIME[ext]
    mime = mime or 'application/octet-stream'
    if len(_MIME_CACHE) < 4096:
        _MIME_CACHE[ext or name] = mime
    return mime


def describe(mime, is_dir=False, is_symlink=False):
    if is_dir:
        return 'Alias to folder' if is_symlink else 'Folder'
    key = mime
    if key in _DESC_CACHE:
        return _DESC_CACHE[key]
    text = ''
    if Gio is not None:
        try:
            text = Gio.content_type_get_description(mime) or ''
        except Exception:
            text = ''
    if not text:
        text = mime.split('/')[-1].replace('x-', '').upper() + ' file' if mime else 'Document'
    _DESC_CACHE[key] = text
    return text


ARCHIVE_MIMES = ('zip', 'tar', 'gzip', 'x-xz', 'bzip', 'x-7z', 'x-rar', 'zstd', 'x-compressed', 'x-cpio',
                 'x-archive', 'java-archive', 'vnd.debian', 'x-rpm', 'x-lzma')
SHEET_MIMES = ('spreadsheet', 'excel', 'csv', 'ms-excel')
SLIDE_MIMES = ('presentation', 'powerpoint')
DOC_MIMES = ('wordprocessing', 'msword', 'rtf', 'opendocument.text', 'epub', 'vnd.oasis.opendocument.text')


def icon_for(mime, is_dir=False, name='', parent_is_home=False, executable=False):
    if is_dir:
        return SPECIAL_DIRS.get(name, 'folder') if parent_is_home else 'folder'
    major, _, minor = mime.partition('/')
    if major == 'image':
        return 'file-image'
    if major == 'audio':
        return 'file-audio'
    if major == 'video':
        return 'file-video'
    if mime == 'application/pdf':
        return 'file-pdf'
    if any(s in minor for s in SHEET_MIMES):
        return 'file-spreadsheet'
    if any(s in minor for s in SLIDE_MIMES):
        return 'file-presentation'
    if any(s in minor for s in DOC_MIMES):
        return 'file-document'
    if any(s in minor for s in ARCHIVE_MIMES):
        return 'file-archive'
    if major == 'font' or 'font' in minor:
        return 'file-font'
    if 'iso9660' in minor or 'disk-image' in minor or 'raw-disk' in minor:
        return 'file-disk-image'
    if major == 'text':
        if minor in ('plain', 'markdown', 'csv'):
            return 'file-text'
        return 'file-code'
    if any(s in minor for s in ('json', 'xml', 'yaml', 'toml', 'javascript', 'x-shellscript', 'x-python', 'sql', 'x-perl', 'x-ruby')):
        return 'file-code'
    if executable and 'executable' in minor or minor in ('x-executable', 'x-sharedlib', 'x-pie-executable'):
        return 'file-executable'
    return 'file-generic'


def entry_from_stat(name, path, st, parent_is_home=False, link_target='', link_st=None, parent=''):
    """Build an Entry from an lstat result (and, for symlinks, the followed stat or None if broken)."""
    is_link = statmod.S_ISLNK(st.st_mode)
    shown = link_st if (is_link and link_st is not None) else st
    is_dir = statmod.S_ISDIR(shown.st_mode)
    mime = 'inode/directory' if is_dir else content_type(name)
    if not is_dir and statmod.S_ISFIFO(shown.st_mode):
        mime = 'inode/fifo'
    elif not is_dir and statmod.S_ISSOCK(shown.st_mode):
        mime = 'inode/socket'
    readable = os.access(path, os.R_OK) if is_dir else True
    entry = Entry(name=name, path=path, is_dir=is_dir, is_symlink=is_link, broken_link=is_link and link_st is None,
                  link_target=link_target, size=0 if is_dir else shown.st_size, mtime=st.st_mtime,
                  btime=getattr(st, 'st_birthtime', 0.0) or 0.0, mode=shown.st_mode, mime=mime,
                  hidden=name.startswith('.'), readable=readable, where=parent)
    entry.kind = 'Broken alias' if entry.broken_link else describe(mime, is_dir, is_link)
    entry.icon = 'file-generic' if entry.broken_link else icon_for(mime, is_dir, name, parent_is_home,
                                                                    bool(shown.st_mode & 0o111))
    return entry


def stat_entry(path, parent_is_home=False):
    path = os.fspath(path)
    st = os.lstat(path)
    target, link_st = '', None
    if statmod.S_ISLNK(st.st_mode):
        try:
            target = os.readlink(path)
        except OSError:
            target = ''
        try:
            link_st = os.stat(path)
        except OSError:
            link_st = None
    return entry_from_stat(os.path.basename(path.rstrip('/')) or '/', path, st, parent_is_home, target, link_st,
                           os.path.dirname(path))


def list_local(path, show_hidden=False, cancel=None, limit=MAX_ENTRIES):
    """Yield Entry for every child of ``path``. Never follows symlinks for recursion.

    Raises FolderError with a human message if the folder cannot be read.
    Individual unreadable children are returned as partial entries instead of aborting.
    """
    path = os.fspath(path)
    home = os.path.realpath(os.path.expanduser('~'))
    parent_is_home = os.path.realpath(path) == home
    try:
        scan = os.scandir(path)
    except OSError as exc:
        raise FolderError(human_error(exc, os.path.basename(path.rstrip('/')) or '/')) from exc
    count = 0
    with scan:
        while True:
            if cancel is not None and cancel.is_set():
                return
            try:
                child = next(scan)
            except StopIteration:
                break
            except OSError as exc:
                raise FolderError(human_error(exc, os.path.basename(path.rstrip('/')) or '/')) from exc
            name = child.name
            if not show_hidden and name.startswith('.'):
                continue
            try:
                st = child.stat(follow_symlinks=False)
            except OSError:
                yield Entry(name=name, path=child.path, kind='Unavailable', readable=False, where=path)
                continue
            target, link_st = '', None
            if statmod.S_ISLNK(st.st_mode):
                try:
                    target = os.readlink(child.path)
                except OSError:
                    target = ''
                try:
                    link_st = child.stat(follow_symlinks=True)
                except OSError:
                    link_st = None
            yield entry_from_stat(name, child.path, st, parent_is_home, target, link_st, path)
            count += 1
            if count >= limit:
                return


# ---------------------------------------------------------------- sorting

_NUM = re.compile(r'(\d+)')


def natural_key(text):
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in _NUM.split(text.casefold()) if p != '']


def sort_entries(entries, key='name', reverse=False, folders_first=True):
    """Return a new sorted list. Stable: ties fall back to natural name order."""
    if key == 'size':
        def k(e): return (e.size, natural_key(e.name))
    elif key == 'modified':
        def k(e): return (e.mtime, natural_key(e.name))
    elif key == 'created':
        def k(e): return (e.btime or e.mtime, natural_key(e.name))
    elif key == 'kind':
        def k(e): return (e.kind.casefold(), natural_key(e.name))
    else:
        def k(e): return natural_key(e.name)
    if folders_first:
        dirs = sorted((e for e in entries if e.is_dir), key=k, reverse=reverse)
        rest = sorted((e for e in entries if not e.is_dir), key=k, reverse=reverse)
        return dirs + rest
    return sorted(entries, key=k, reverse=reverse)


def entry_less(a, b, key='name', reverse=False, folders_first=True):
    """Ordering predicate matching sort_entries (used for incremental insertion into a sorted list)."""
    if folders_first and a.is_dir != b.is_dir:
        return a.is_dir
    def k(e):
        if key == 'size':
            return (e.size, natural_key(e.name))
        if key == 'modified':
            return (e.mtime, natural_key(e.name))
        if key == 'created':
            return (e.btime or e.mtime, natural_key(e.name))
        if key == 'kind':
            return (e.kind.casefold(), natural_key(e.name))
        return natural_key(e.name)
    ka, kb = k(a), k(b)
    return ka > kb if reverse else ka < kb


# ---------------------------------------------------------------- formatting

def human_size(n):
    if n is None or n < 0:
        return '--'
    if n < 1000:
        return f'{n} byte' + ('' if n == 1 else 's')
    value = float(n)
    for unit in ('KB', 'MB', 'GB', 'TB', 'PB'):
        value /= 1000
        if value < 1000 or unit == 'PB':
            return f'{value:.1f} {unit}' if value < 100 else f'{value:.0f} {unit}'


def format_date(ts, now=None):
    if not ts:
        return '--'
    now = now or time.time()
    lt, ln = time.localtime(ts), time.localtime(now)
    day = (lt.tm_year, lt.tm_yday)
    if day == (ln.tm_year, ln.tm_yday):
        return time.strftime('Today, %H:%M', lt)
    yesterday = time.localtime(now - 86400)
    if day == (yesterday.tm_year, yesterday.tm_yday):
        return time.strftime('Yesterday, %H:%M', lt)
    if lt.tm_year == ln.tm_year:
        return time.strftime('%d %b, %H:%M', lt)
    return time.strftime('%d %b %Y', lt)


def mode_string(mode):
    return statmod.filemode(mode)


# ---------------------------------------------------------------- recursive size

def folder_size(path, cancel=None, max_items=5_000_000):
    """Return (bytes, files, folders, complete). Never follows symlinks; bounded; cancellable."""
    total = files = folders = 0
    seen = set()
    stack = [os.fspath(path)]
    complete = True
    while stack:
        if cancel is not None and cancel.is_set():
            return total, files, folders, False
        directory = stack.pop()
        try:
            with os.scandir(directory) as scan:
                for child in scan:
                    try:
                        st = child.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if statmod.S_ISDIR(st.st_mode):
                        key = (st.st_dev, st.st_ino)
                        if key in seen:
                            continue
                        seen.add(key)
                        folders += 1
                        stack.append(child.path)
                    else:
                        files += 1
                        total += st.st_blocks * 512 if hasattr(st, 'st_blocks') and st.st_blocks else st.st_size
                    if files + folders > max_items:
                        return total, files, folders, False
        except OSError:
            complete = False
    return total, files, folders, complete


def count_children(path, cap=100000):
    n = 0
    try:
        with os.scandir(path) as scan:
            for _ in scan:
                n += 1
                if n >= cap:
                    break
    except OSError:
        return None
    return n


def unique_name(directory, name, suffix=' copy'):
    """Return a name that does not exist in directory: 'a copy.txt', 'a copy 2.txt'."""
    directory = os.fspath(directory)
    stem, ext = split_name(name)
    candidate = f'{stem}{suffix}{ext}'
    n = 2
    while os.path.lexists(os.path.join(directory, candidate)):
        candidate = f'{stem}{suffix} {n}{ext}'
        n += 1
    return candidate


def split_name(name):
    if name.startswith('.') and name.count('.') == 1:
        return name, ''
    for double in ('.tar.gz', '.tar.xz', '.tar.bz2', '.tar.zst'):
        if name.lower().endswith(double):
            return name[:-len(double)], name[-len(double):]
    stem, ext = os.path.splitext(name)
    if not stem:
        return name, ''
    return stem, ext


def valid_name(name):
    """Return an error string for an unacceptable file name or None."""
    if not name or not name.strip():
        return 'Type a name.'
    if name in ('.', '..'):
        return 'That name is reserved.'
    if '/' in name or '\0' in name:
        return 'A name cannot contain “/”.'
    if len(name.encode('utf-8', 'surrogateescape')) > 255:
        return 'That name is too long.'
    return None


class Cancelled(Exception):
    pass


def new_cancel():
    return threading.Event()
