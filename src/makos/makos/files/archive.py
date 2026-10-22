"""Compress and extract zip / tar archives with Python's standard libraries only.

Extraction is hostile-input safe: no absolute or ``..`` paths, no symlinks pointing outside the
destination, no devices or hard links, no writing through symlinks, bounded member count and
uncompressed size, free-space check, and output goes to a temporary folder that is renamed on success.
"""
import os
import shutil
import stat
import tarfile
import time
import zipfile
from pathlib import PurePosixPath

SUFFIX = {'zip': '.zip', 'tar.gz': '.tar.gz', 'tar.xz': '.tar.xz', 'tar.bz2': '.tar.bz2'}
FORMATS = tuple(SUFFIX)
MAX_MEMBERS = 1_000_000
MAX_TOTAL = 64 * 2 ** 30
CHUNK = 256 * 1024


class ArchiveError(Exception):
    pass


class _Cancel(Exception):
    pass


def strip_suffix(name):
    low = name.lower()
    for suffix in ('.tar.gz', '.tar.xz', '.tar.bz2', '.tar.zst', '.tgz', '.txz', '.tbz2', '.tar', '.zip', '.jar', '.gz', '.xz', '.bz2'):
        if low.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name + ' extracted'


def is_archive(path):
    try:
        return zipfile.is_zipfile(path) or tarfile.is_tarfile(path)
    except OSError:
        return False


# ---------------------------------------------------------------- compress

def _walk(path):
    """Yield (full_path, archive_name_relative_to_parent). Never follows symlinks."""
    base = os.path.dirname(os.path.abspath(path.rstrip('/')))
    stack = [os.path.abspath(path.rstrip('/'))]
    while stack:
        cur = stack.pop()
        yield cur, os.path.relpath(cur, base)
        try:
            st = os.lstat(cur)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            try:
                names = sorted(os.listdir(cur), reverse=True)
            except OSError:
                continue
            stack.extend(os.path.join(cur, n) for n in names)


def compress(sources, dest, fmt='zip', progress=None, cancel=None):
    if fmt not in SUFFIX:
        raise ArchiveError('Unsupported archive format.')
    if not sources:
        raise ArchiveError('Nothing to compress.')
    part = dest + '.part'
    dest_real = os.path.realpath(dest)
    try:
        if fmt == 'zip':
            with zipfile.ZipFile(part, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
                for src in sources:
                    for full, arc in _walk(src):
                        if cancel and cancel():
                            raise _Cancel()
                        if os.path.realpath(full) in (dest_real, os.path.realpath(part)):
                            continue
                        st = os.lstat(full)
                        if stat.S_ISLNK(st.st_mode):
                            zi = zipfile.ZipInfo(arc, time.localtime(st.st_mtime)[:6])
                            zi.create_system = 3
                            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                            zf.writestr(zi, os.readlink(full))
                        elif stat.S_ISDIR(st.st_mode):
                            zf.write(full, arc.rstrip('/') + '/')
                        elif stat.S_ISREG(st.st_mode):
                            zf.write(full, arc)
                            if progress:
                                progress(st.st_size)
        else:
            mode = {'tar.gz': 'w:gz', 'tar.xz': 'w:xz', 'tar.bz2': 'w:bz2'}[fmt]
            with tarfile.open(part, mode) as tf:
                for src in sources:
                    for full, arc in _walk(src):
                        if cancel and cancel():
                            raise _Cancel()
                        if os.path.realpath(full) in (dest_real, os.path.realpath(part)):
                            continue
                        st = os.lstat(full)
                        if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode)):
                            continue
                        tf.add(full, arc, recursive=False)
                        if progress and stat.S_ISREG(st.st_mode):
                            progress(st.st_size)
        os.replace(part, dest)
    except _Cancel:
        _quiet_remove(part)
        from .model import Cancelled
        raise Cancelled() from None
    except OSError as exc:
        _quiet_remove(part)
        from .model import human_error
        raise ArchiveError(human_error(exc, os.path.basename(dest))) from exc
    except Exception:
        _quiet_remove(part)
        raise
    return dest


def _quiet_remove(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------- listing

def list_archive(path, limit=2000):
    """Return (entries, total, truncated); entries are (name, size, is_dir). Reads only the index."""
    entries, total = [], 0
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                infos = zf.infolist()
                total = len(infos)
                for zi in infos[:limit]:
                    entries.append((zi.filename, zi.file_size, zi.is_dir()))
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as tf:
                for member in tf:
                    total += 1
                    if len(entries) < limit:
                        entries.append((member.name, member.size, member.isdir()))
                    if total >= limit * 5:
                        total = -total   # unknown, large
                        break
        else:
            raise ArchiveError('This archive format cannot be listed here.')
    except (OSError, zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
        raise ArchiveError('This archive is damaged or unreadable.') from exc
    return entries, abs(total), total < 0 or total > limit


# ---------------------------------------------------------------- extract

def safe_parts(name):
    """Return normalized relative path parts or None if the member name is unsafe."""
    name = name.replace('\\', '/')
    if not name or '\0' in name or name.startswith('/') or (len(name) > 1 and name[1] == ':'):
        return None
    parts = [p for p in PurePosixPath(name).parts if p not in ('.', '')]
    if not parts or any(p == '..' for p in parts):
        return None
    return parts


def _link_ok(parts, target):
    """True if a symlink at ``parts`` pointing to ``target`` stays inside the extraction root."""
    if target.startswith('/') or '\0' in target:
        return False
    depth = len(parts) - 1
    for p in PurePosixPath(target).parts:
        if p == '..':
            depth -= 1
            if depth < 0:
                return False
        elif p != '.':
            depth += 1
    return True


def _inside(root, path):
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    return path == root or path.startswith(root.rstrip('/') + '/')


def extract(path, dest, progress=None, cancel=None):
    """Extract ``path`` into the new folder ``dest`` (must not exist). Returns ``dest``."""
    if os.path.lexists(dest):
        raise ArchiveError('The destination already exists.')
    parent = os.path.dirname(os.path.abspath(dest))
    temp = os.path.join(parent, '.' + os.path.basename(dest) + '.makos-part')
    if os.path.lexists(temp):
        shutil.rmtree(temp, ignore_errors=True)
    try:
        os.mkdir(temp, 0o700)
        if zipfile.is_zipfile(path):
            _extract_zip(path, temp, parent, progress, cancel)
        elif tarfile.is_tarfile(path):
            _extract_tar(path, temp, parent, progress, cancel)
        else:
            raise ArchiveError('This archive format is not supported.')
        os.chmod(temp, 0o755)
        entries = os.listdir(temp)
        if len(entries) == 1 and os.path.isdir(os.path.join(temp, entries[0])) and not os.path.islink(os.path.join(temp, entries[0])):
            os.rename(os.path.join(temp, entries[0]), dest)
            os.rmdir(temp)
        else:
            os.rename(temp, dest)
    except _Cancel:
        shutil.rmtree(temp, ignore_errors=True)
        from .model import Cancelled
        raise Cancelled() from None
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, NotImplementedError, RuntimeError) as exc:
        shutil.rmtree(temp, ignore_errors=True)
        raise ArchiveError('This archive is damaged, encrypted or uses an unsupported method.') from exc
    except OSError as exc:
        shutil.rmtree(temp, ignore_errors=True)
        from .model import human_error
        raise ArchiveError(human_error(exc, os.path.basename(path))) from exc
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return dest


def _check_budget(count, total, parent):
    if count > MAX_MEMBERS:
        raise ArchiveError('This archive contains too many items to extract safely.')
    if total > MAX_TOTAL:
        raise ArchiveError('This archive would expand to more than 64 GB, so it was not extracted.')
    try:
        free = shutil.disk_usage(parent).free
    except OSError:
        return
    if total > free:
        raise ArchiveError('There is not enough free space to extract this archive.')


def _extract_zip(path, root, parent, progress, cancel):
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        _check_budget(len(infos), sum(i.file_size for i in infos), parent)
        for zi in infos:
            if cancel and cancel():
                raise _Cancel()
            if zi.flag_bits & 0x1:
                raise ArchiveError('This archive is password protected.')
            parts = safe_parts(zi.filename)
            if parts is None:
                raise ArchiveError(f'Unsafe path in archive: “{zi.filename}”. Nothing was extracted.')
            target = os.path.join(root, *parts)
            if not _inside(root, os.path.dirname(target)):
                raise ArchiveError(f'Unsafe path in archive: “{zi.filename}”. Nothing was extracted.')
            mode = (zi.external_attr >> 16) & 0xFFFF
            if zi.is_dir():
                os.makedirs(target, mode=0o755, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
            if not _inside(root, os.path.dirname(target)):
                raise ArchiveError(f'Unsafe path in archive: “{zi.filename}”. Nothing was extracted.')
            if stat.S_ISLNK(mode):
                link = zf.read(zi).decode('utf-8', 'replace')
                if not _link_ok(parts, link):
                    continue     # silently drop links that would escape the folder
                os.symlink(link, target)
                continue
            if mode and not (stat.S_ISREG(mode) or mode & 0o170000 == 0):
                continue         # devices, sockets, fifos
            written = 0
            with zf.open(zi) as src, open(target, 'xb') as out:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > zi.file_size + CHUNK:
                        raise ArchiveError('Archive contents do not match their declared size; extraction stopped.')
                    out.write(chunk)
                    if cancel and cancel():
                        raise _Cancel()
            perm = (mode & 0o777) if mode else 0o644
            os.chmod(target, (perm | 0o600) & 0o755 if perm & 0o111 else (perm | 0o600) & 0o644)
            if progress:
                progress(written, target)


def _extract_tar(path, root, parent, progress, cancel):
    with tarfile.open(path) as tf:
        members = []
        total = 0
        for member in tf:
            members.append(member)
            total += max(member.size, 0)
            if len(members) > MAX_MEMBERS:
                raise ArchiveError('This archive contains too many items to extract safely.')
            if total > MAX_TOTAL:
                raise ArchiveError('This archive would expand to more than 64 GB, so it was not extracted.')
        _check_budget(len(members), total, parent)
        for member in members:
            if cancel and cancel():
                raise _Cancel()
            parts = safe_parts(member.name)
            if parts is None:
                raise ArchiveError(f'Unsafe path in archive: “{member.name}”. Nothing was extracted.')
            if member.islnk() or member.isdev() or member.isfifo():
                continue     # hard links and special files are never created
            if member.issym() and not _link_ok(parts, member.linkname):
                continue
            target = os.path.join(root, *parts)
            if not _inside(root, os.path.dirname(target)):
                raise ArchiveError(f'Unsafe path in archive: “{member.name}”. Nothing was extracted.')
            member.name = '/'.join(parts)
            kwargs = {'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}
            try:
                tf.extract(member, root, **kwargs)
            except tarfile.FilterError:
                continue
            if progress and member.isreg():
                progress(member.size, target)
