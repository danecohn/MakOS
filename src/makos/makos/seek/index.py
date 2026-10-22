"""Seek's fallback file index: sqlite FTS5 over file names (and the text of small text files) in the user's own folders.

Safety rules (tested): only the folders in ROOTS are walked, hidden files/directories are never indexed, known secret
locations (~/.ssh ~/.gnupg ~/.claude ~/.codex ~/.openclaw, browser profiles, key/password files) are excluded even if a root
points at them, symbolic links are never followed, and a user exclusion list is honoured. The indexer runs in a separate
low-priority process (`python3 -m makos.seek.index`) so it can never stall the shell; it keeps the index fresh with inotify.
"""
import ctypes
import ctypes.util
import fnmatch
import os
import platform
import re
import select
import sqlite3
import struct
import sys
import time
from pathlib import Path

ROOT_NAMES = ('Documents', 'Desktop', 'Downloads', 'Pictures', 'Music')
SECRET_DIRS = ('.ssh', '.gnupg', '.claude', '.codex', '.openclaw', '.mozilla', '.config/google-chrome', '.config/chromium', '.config/BraveSoftware',
               '.config/microsoft-edge', '.var', '.password-store', '.aws', '.kube', '.docker', '.local/share/keyrings', 'snap')
SECRET_FILES = ('id_rsa*', 'id_ed25519*', 'id_ecdsa*', '*.pem', '*.key', '*.kdbx', '*.p12', '*.pfx', '*.gpg', '*.asc', '.env*', 'credentials*',
                '*.keystore', '*.jks', 'known_hosts', 'secrets*', '*.token')
TEXT_EXT = {'.txt', '.md', '.rst', '.csv', '.log', '.json', '.xml', '.html', '.htm', '.py', '.js', '.css', '.c', '.h', '.cpp', '.rs', '.go',
            '.sh', '.tex', '.yaml', '.yml', '.toml', '.ini', '.org', '.srt', '.vcf', '.ics'}
MAX_TEXT_BYTES = 200_000
MAX_FILES = 200_000
MAX_WATCHES = 4096
BATCH = 400


def db_path():
    from .. import common
    return common.STATE / 'seek-index.sqlite'


def default_roots(home=None):
    home = Path(home or Path.home())
    return [home / n for n in ROOT_NAMES]


def is_secret_name(name):
    return any(fnmatch.fnmatchcase(name.lower(), pat.lower()) for pat in SECRET_FILES)


def is_excluded(path, home=None, exclusions=()):
    """True when `path` (a file or directory) must never be indexed."""
    home = Path(home or Path.home())
    p = Path(path)
    try:
        rel = p.relative_to(home)
        parts = rel.parts
    except ValueError:
        parts = p.parts[1:] if p.is_absolute() else p.parts
        rel = None
    if any(part.startswith('.') for part in parts):
        return True
    if rel is not None:
        rels = rel.as_posix()
        for secret in SECRET_DIRS:
            if rels == secret or rels.startswith(secret + '/'):
                return True
    if is_secret_name(p.name):
        return True
    ps = str(p)
    for ex in exclusions or ():
        ex = str(ex).rstrip('/')
        if ex and (ps == ex or ps.startswith(ex + '/')):
            return True
    return False


def fts_query(text):
    """Turn user text into a safe FTS5 query: every word becomes a quoted prefix term; punctuation never reaches the parser."""
    words = re.findall(r'\w+', text.casefold(), re.UNICODE)[:8]
    if not words:
        return None
    return ' '.join('"%s"*' % w.replace('"', '') for w in words)


class Index:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.db.execute('pragma journal_mode=wal')
        self.db.execute('create table if not exists files(path text primary key, name text, mtime real, size integer)')
        self.db.execute("create virtual table if not exists fts using fts5(name, body, path unindexed, tokenize='unicode61 remove_diacritics 2')")
        self.db.execute('create table if not exists meta(key text primary key, value text)')
        self.db.commit()

    def close(self):
        self.db.close()

    # ---- writes
    def _read_text(self, path, size):
        if Path(path).suffix.lower() in TEXT_EXT and size <= MAX_TEXT_BYTES:
            try:
                with open(path, 'rb') as f:
                    raw = f.read(MAX_TEXT_BYTES)
                if b'\0' not in raw[:2048]:
                    return raw.decode('utf-8', errors='ignore')
            except OSError:
                pass
        return ''

    def upsert(self, path, commit=True):
        try:
            st = os.lstat(path)
        except OSError:
            self.remove(path, commit)
            return False
        if not os.path.isfile(path) or os.path.islink(path):
            return False
        row = self.db.execute('select mtime,size from files where path=?', (str(path),)).fetchone()
        if row and row[0] == st.st_mtime and row[1] == st.st_size:
            return False
        self.remove(path, commit=False)
        name = os.path.basename(path)
        self.db.execute('insert into files values(?,?,?,?)', (str(path), name, st.st_mtime, st.st_size))
        self.db.execute('insert into fts(name,body,path) values(?,?,?)', (name + ' ' + re.sub(r'[_\-.]+', ' ', name), self._read_text(path, st.st_size), str(path)))
        if commit:
            self.db.commit()
        return True

    def remove(self, path, commit=True):
        self.db.execute('delete from fts where path=?', (str(path),))
        self.db.execute('delete from files where path=?', (str(path),))
        if commit:
            self.db.commit()

    def remove_tree(self, directory):
        like = str(directory).rstrip('/') + '/%'
        self.db.execute('delete from fts where path like ?', (like,))
        self.db.execute('delete from files where path like ?', (like,))
        self.db.commit()

    def count(self):
        return self.db.execute('select count(*) from files').fetchone()[0]

    def set_meta(self, key, value):
        self.db.execute('insert or replace into meta values(?,?)', (key, str(value)))
        self.db.commit()

    def meta(self, key, default=None):
        row = self.db.execute('select value from meta where key=?', (key,)).fetchone()
        return row[0] if row else default

    # ---- reads
    def search(self, text, limit=30):
        """[{'path','name','snippet'}] best matches first (file-name hits outrank body-only hits)."""
        q = fts_query(text)
        if not q:
            return []
        try:
            rows = self.db.execute(
                "select path, name, snippet(fts, 1, '', '', '…', 10), bm25(fts, 8.0, 1.0) as r from fts where fts match ? order by r limit ?",
                (q, int(limit))).fetchall()
        except sqlite3.OperationalError:
            return []
        out = []
        for path, name, snip, _rank in rows:
            if os.path.exists(path):
                out.append({'path': path, 'name': os.path.basename(path), 'snippet': snip.strip()})
        return out

    # ---- scanning
    def scan(self, roots, home=None, exclusions=(), throttle=0.0, limit=MAX_FILES):
        """Index (or refresh) everything under the roots; remove entries whose files disappeared. Returns the number of changed files."""
        home = Path(home or Path.home())
        seen, changed, n = set(), 0, 0
        for root in roots:
            root = Path(root)
            if not root.is_dir() or root.is_symlink() or is_excluded(root, home, exclusions):
                continue
            for directory, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not is_excluded(Path(directory) / d, home, exclusions) and not (Path(directory) / d).is_symlink())
                for name in sorted(files):
                    full = Path(directory) / name
                    if is_excluded(full, home, exclusions):
                        continue
                    seen.add(str(full))
                    n += 1
                    if n > limit:
                        break
                    if self.upsert(str(full), commit=False):
                        changed += 1
                    if n % BATCH == 0:
                        self.db.commit()
                        if throttle:
                            time.sleep(throttle)
        self.db.commit()
        # drop vanished files (only those below the scanned roots)
        prefixes = tuple(str(Path(r)) + '/' for r in roots)
        for (path,) in self.db.execute('select path from files').fetchall():
            if path.startswith(prefixes) and path not in seen:
                self.remove(path, commit=False)
                changed += 1
        self.db.commit()
        self.set_meta('last_scan', int(time.time()))
        return changed


# ---------------------------------------------------------------- inotify (ctypes; no third-party module)
IN_MODIFY, IN_CLOSE_WRITE, IN_MOVED_FROM, IN_MOVED_TO, IN_CREATE, IN_DELETE, IN_DELETE_SELF = 0x2, 0x8, 0x40, 0x80, 0x100, 0x200, 0x400
IN_ISDIR, IN_Q_OVERFLOW = 0x40000000, 0x4000
WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_DELETE_SELF


class Watcher:
    """Keeps an Index current. step(timeout) processes pending events; the indexer process calls it in a loop."""

    def __init__(self, index, roots, home=None, exclusions=()):
        libc = ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6', use_errno=True)
        self.libc = libc
        self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), 'inotify unavailable')
        self.index, self.home, self.exclusions = index, Path(home or Path.home()), exclusions
        self.watches = {}
        for root in roots:
            self.add_tree(Path(root))

    def add_tree(self, root):
        if not root.is_dir() or root.is_symlink() or is_excluded(root, self.home, self.exclusions):
            return
        for directory, dirs, _files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not is_excluded(Path(directory) / d, self.home, self.exclusions) and not (Path(directory) / d).is_symlink()]
            if len(self.watches) >= MAX_WATCHES:
                return
            wd = self.libc.inotify_add_watch(self.fd, os.fsencode(directory), WATCH_MASK)
            if wd >= 0:
                self.watches[wd] = directory

    def step(self, timeout=1.0):
        """Handle queued events; returns the number of index changes."""
        if not select.select([self.fd], [], [], timeout)[0]:
            return 0
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return 0
        changes, pos = 0, 0
        while pos + 16 <= len(data):
            wd, mask, _cookie, length = struct.unpack_from('iIII', data, pos)
            name = data[pos + 16:pos + 16 + length].split(b'\0', 1)[0].decode('utf-8', 'surrogateescape')
            pos += 16 + length
            base = self.watches.get(wd)
            if mask & IN_Q_OVERFLOW:
                changes += self.index.scan([r for r in self.watches.values()], self.home, self.exclusions)
                continue
            if not base or not name:
                continue
            full = os.path.join(base, name)
            if is_excluded(full, self.home, self.exclusions):
                continue
            if mask & IN_ISDIR:
                if mask & (IN_CREATE | IN_MOVED_TO):
                    self.add_tree(Path(full))
                    changes += self.index.scan([full], self.home, self.exclusions)
                elif mask & (IN_DELETE | IN_MOVED_FROM):
                    self.index.remove_tree(full)
                    changes += 1
            elif mask & (IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE):
                changes += 1 if self.index.upsert(full) else 0
            elif mask & (IN_DELETE | IN_MOVED_FROM):
                self.index.remove(full)
                changes += 1
        return changes

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


# ---------------------------------------------------------------- low-priority background process
def lower_priority():
    """Nice 19 and idle I/O class for this process (best effort; failures are ignored)."""
    try:
        os.nice(19)
    except OSError:
        pass
    try:
        number = {'aarch64': 30, 'x86_64': 251, 'armv7l': 314}.get(platform.machine())
        if number:
            libc = ctypes.CDLL(None, use_errno=True)
            libc.syscall(number, 1, 0, (3 << 13))  # IOPRIO_WHO_PROCESS, self, IOPRIO_CLASS_IDLE
    except Exception:  # noqa: BLE001
        pass


def main(argv=None):
    """`python3 -m makos.seek.index [--once]`: build or refresh the index, then follow changes until the parent exits."""
    argv = list(sys.argv[1:] if argv is None else argv)
    from .. import common
    lower_priority()
    settings = common.load_settings()
    exclusions = settings.get('seek_exclusions', [])
    roots = default_roots()
    index = Index(db_path())
    index.scan(roots, exclusions=exclusions, throttle=0.02)
    if '--once' in argv:
        return 0
    parent = os.getppid()
    try:
        watcher = Watcher(index, roots, exclusions=exclusions)
    except OSError:
        return 0
    while os.getppid() == parent:
        watcher.step(2.0)
    return 0


def spawn():
    """Start the indexer detached from the shell (never blocks, never inherits the layer-shell preload). Returns the Popen or None."""
    import subprocess
    env = dict(os.environ)
    env.pop('LD_PRELOAD', None)
    from .. import common
    env['PYTHONPATH'] = os.pathsep.join([str(common.SOURCE)] + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
    try:
        return subprocess.Popen([sys.executable, '-m', 'makos.seek.index'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL)
    except OSError:
        return None


if __name__ == '__main__':
    sys.exit(main())
