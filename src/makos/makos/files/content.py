"""Bounded, never-executing content previews. GTK-free except GdkPixbuf thumbnails.

Rules: every read is size-capped; every subprocess runs with a timeout, a scrubbed
environment, its own session (killed as a group), resource limits, and — for LibreOffice —
inside a bubblewrap sandbox (no network, no home directory, read-only system) when available.
Nothing in a previewed file is ever executed or opened by a launcher.
"""
import hashlib
import io
import os
import re
import shutil
import signal
import stat as statmod
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from . import archive, model

TEXT_LIMIT = 256 * 1024
IMAGE_LIMIT = 80 * 1024 * 1024
OFFICE_LIMIT = 60 * 1024 * 1024
PDF_LIMIT = 300 * 1024 * 1024
THUMB_PX = 512
TIMEOUT_PDF = 12
TIMEOUT_OFFICE = 40

OFFICE_MIMES = ('opendocument', 'msword', 'ms-excel', 'ms-powerpoint', 'officedocument', 'rtf', 'vnd.sun.xml', 'wordperfect', 'abiword')
CODE_EXT = {'.py', '.js', '.ts', '.c', '.h', '.cc', '.cpp', '.hpp', '.rs', '.go', '.java', '.sh', '.bash', '.css', '.html', '.xml',
            '.json', '.yml', '.yaml', '.toml', '.ini', '.md', '.lua', '.rb', '.php', '.sql', '.cfg', '.conf', '.desktop', '.gd', '.qml', '.cs', '.kt'}


def cache_dir():
    base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'makos' / 'files-thumbs'
    return base


def classify(path):
    """Return one of folder, image, pdf, audio, video, office, archive, text, other."""
    path = os.fspath(path)
    try:
        st = os.stat(path)
    except OSError:
        return 'other'
    if statmod.S_ISDIR(st.st_mode):
        return 'folder'
    if not statmod.S_ISREG(st.st_mode):
        return 'other'
    mime = model.content_type(os.path.basename(path))
    major, _, minor = mime.partition('/')
    if major == 'image' and 'svg' not in minor or minor == 'svg+xml':
        return 'image'
    if mime == 'application/pdf':
        return 'pdf'
    if major == 'audio':
        return 'audio'
    if major == 'video':
        return 'video'
    if any(m in minor for m in OFFICE_MIMES):
        return 'office'
    if any(m in minor for m in archive_mimes()) or archive.is_archive(path) and not major == 'text':
        return 'archive'
    if major == 'text' or os.path.splitext(path)[1].lower() in CODE_EXT or 'json' in minor or 'xml' in minor or 'x-shellscript' in minor:
        return 'text'
    if sniff_text(path):
        return 'text'
    return 'other'


def archive_mimes():
    return ('zip', 'x-tar', 'gzip', 'x-xz', 'x-bzip', 'x-7z', 'x-compressed-tar', 'x-cpio', 'java-archive', 'x-rar')


def sniff_text(path, probe=4096):
    try:
        with open(path, 'rb') as stream:
            head = stream.read(probe)
    except OSError:
        return False
    if not head:
        return True
    if b'\0' in head:
        return False
    try:
        head.decode('utf-8')
        return True
    except UnicodeDecodeError as exc:
        return exc.start >= len(head) - 4        # cut inside a multibyte character at the probe edge


def read_text(path, limit=TEXT_LIMIT):
    """Return (text, truncated). Never raises for undecodable bytes."""
    with open(path, 'rb') as stream:
        raw = stream.read(limit + 1)
    truncated = len(raw) > limit
    raw = raw[:limit]
    text = raw.decode('utf-8', 'replace')
    if truncated:
        text = text.rsplit('\n', 1)[0] if '\n' in text else text
    return text, truncated


# ------------------------------------------------------------- syntax-light highlighting

KEYWORDS = {
    'py': 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield match case',
    'js': 'async await break case catch class const continue default delete do else export extends false finally for function if import in instanceof let new null return static super switch this throw true try typeof var void while yield interface type enum',
    'c': 'auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while class namespace template public private protected virtual new delete this true false nullptr fn let mut pub impl use mod match loop self',
    'sh': 'if then else elif fi for while do done case esac function in return export local readonly echo exit',
    'css': '', 'json': 'true false null', 'md': '', 'html': '',
}
LANG_BY_EXT = {'.py': 'py', '.js': 'js', '.ts': 'js', '.java': 'c', '.cs': 'c', '.kt': 'c', '.go': 'c', '.c': 'c', '.h': 'c', '.cc': 'c',
               '.cpp': 'c', '.hpp': 'c', '.rs': 'c', '.gd': 'py', '.sh': 'sh', '.bash': 'sh', '.css': 'css', '.json': 'json',
               '.md': 'md', '.html': 'html', '.xml': 'html', '.qml': 'js', '.yml': 'sh', '.yaml': 'sh', '.toml': 'sh', '.ini': 'sh',
               '.conf': 'sh', '.desktop': 'sh', '.rb': 'sh', '.lua': 'sh', '.php': 'c', '.sql': 'c'}
HASH_COMMENT = {'py', 'sh'}


def language_for(name):
    return LANG_BY_EXT.get(os.path.splitext(name)[1].lower())


def highlight_spans(text, lang, max_chars=120000):
    """Return [(start, end, tag)] with tag in comment, string, number, keyword. Light and linear-time."""
    if not lang:
        return []
    text = text[:max_chars]
    comment = r'#[^\n]*' if lang in HASH_COMMENT else (r'<!--.*?-->' if lang in ('html', 'md') else r'//[^\n]*|/\*.*?\*/')
    if lang == 'md':
        parts = [('keyword', r'^#{1,6} [^\n]*'), ('string', r'`[^`\n]+`')]
    else:
        words = KEYWORDS.get(lang, '').split()
        parts = [('comment', comment), ('string', r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')]
        parts.append(('number', r'\b\d+(?:\.\d+)?\b'))
        if words:
            parts.append(('keyword', r'\b(?:' + '|'.join(map(re.escape, words)) + r')\b'))
        if lang == 'html':
            parts.append(('keyword', r'</?[A-Za-z][^>\n]*>'))
    pattern = re.compile('|'.join(f'(?P<{tag}{i}>{rx})' for i, (tag, rx) in enumerate(parts)), re.S | re.M)
    spans = []
    for m in pattern.finditer(text):
        spans.append((m.start(), m.end(), re.sub(r'\d+$', '', m.lastgroup)))
    return spans


# ------------------------------------------------------------- bounded subprocesses

def _scrubbed_env(extra=None):
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': tempfile.gettempdir(), 'LC_ALL': 'C.UTF-8'}
    env.update(extra or {})
    return env


def run_bounded(argv, timeout, cwd=None, env=None, max_output=64 * 1024 * 1024, mem=4 * 2 ** 30, cpu=None):
    """Run argv without a shell. Returns (returncode, stdout bytes) or raises TimeoutError.

    The child gets its own session so that the whole process tree is killed on timeout.
    """
    argv = list(argv)
    if shutil.which('prlimit'):
        argv = ['prlimit', f'--as={mem}', f'--cpu={cpu or int(timeout) + 5}', '--core=0', f'--fsize={max_output}', '--'] + argv
    proc = subprocess.Popen(argv, cwd=cwd, env=env or _scrubbed_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        raise TimeoutError('The preview took too long and was stopped.') from None
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)       # stray grandchildren
        except OSError:
            pass
    return proc.returncode, out[:max_output]


_BWRAP = None


def bwrap_works():
    global _BWRAP
    if _BWRAP is None:
        exe = shutil.which('bwrap')
        _BWRAP = False
        if exe:
            try:
                rc, _ = run_bounded([exe, '--ro-bind', '/', '/', '--unshare-all', '--die-with-parent', 'true'], 5)
                _BWRAP = rc == 0
            except Exception:
                _BWRAP = False
    return _BWRAP


def sandbox_argv(inner, work, ro_inputs):
    """Wrap ``inner`` in bubblewrap: no network, hidden home, read-only system, writable ``work`` only."""
    argv = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp', '--tmpfs', '/home',
            '--tmpfs', '/root', '--tmpfs', '/run', '--bind', work, '/tmp/work']
    for host, name in ro_inputs:
        argv += ['--ro-bind', host, f'/tmp/work/{name}']
    argv += ['--unshare-all', '--die-with-parent', '--new-session', '--clearenv', '--setenv', 'HOME', '/tmp/work/home',
             '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8']
    return argv + inner


# ------------------------------------------------------------- thumbnails

def thumb_key(path, st=None, extra=''):
    st = st or os.stat(path)
    return hashlib.sha256(f'{os.path.realpath(path)}|{st.st_mtime_ns}|{st.st_size}|{extra}'.encode()).hexdigest()[:40]


def cached(path, extra=''):
    try:
        key = thumb_key(path, extra=extra)
    except OSError:
        return None, None
    return cache_dir() / f'{key}.png', key


def pdf_pages(path):
    if not shutil.which('pdfinfo'):
        return 0
    try:
        rc, out = run_bounded(['pdfinfo', '--', os.fspath(path)], 8, max_output=1 << 20)
    except TimeoutError:
        return 0
    m = re.search(rb'^Pages:\s+(\d+)', out, re.M)
    return int(m.group(1)) if m else 0


def pdf_page_png(path, page=1, width=900):
    """Render one page to PNG bytes using pdftoppm (poppler) with a time limit. None if unavailable."""
    exe = shutil.which('pdftoppm')
    if not exe or os.path.getsize(path) > PDF_LIMIT:
        return None
    store, _key = cached(path, f'pdf{page}x{width}')
    if store and store.exists():
        return store.read_bytes()
    with tempfile.TemporaryDirectory(prefix='makos-pdf-') as work:
        root = os.path.join(work, 'page')
        rc, _ = run_bounded([exe, '-png', '-f', str(page), '-l', str(page), '-singlefile', '-scale-to', str(width),
                             os.fspath(path), root], TIMEOUT_PDF, cwd=work, max_output=64 * 1024 * 1024)
        out = root + '.png'
        if rc != 0 or not os.path.exists(out):
            return None
        data = Path(out).read_bytes()
    if store:
        _save_cache(store, data)
    return data


def _save_cache(store, data):
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        tmp = store.with_suffix('.tmp')
        tmp.write_bytes(data)
        tmp.replace(store)
    except OSError:
        pass


def embedded_office_thumbnail(path):
    """PNG/JPEG bytes from an ODF/OOXML package thumbnail (no external program needed)."""
    try:
        if not zipfile.is_zipfile(path):
            return None
        with zipfile.ZipFile(path) as zf:
            for name in ('Thumbnails/thumbnail.png', 'docProps/thumbnail.jpeg', 'docProps/thumbnail.png', 'docProps/thumbnail.jpg'):
                try:
                    info = zf.getinfo(name)
                except KeyError:
                    continue
                if info.file_size < 4 * 1024 * 1024:
                    return zf.read(info)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        pass
    return None


def office_thumbnail(path, allow_soffice=True):
    """First-page PNG bytes: embedded thumbnail, else sandboxed headless LibreOffice, else None."""
    path = os.fspath(path)
    store, _key = cached(path, 'office')
    if store and store.exists():
        return store.read_bytes()
    data = embedded_office_thumbnail(path)
    if data is None and allow_soffice and shutil.which('soffice') and os.path.getsize(path) <= OFFICE_LIMIT:
        data = _soffice_png(path)
    if data and store:
        _save_cache(store, data)
    return data


def _soffice_png(path):
    ext = os.path.splitext(path)[1][:12] or '.bin'
    ext = re.sub(r'[^A-Za-z0-9.]', '', ext) or '.bin'
    with tempfile.TemporaryDirectory(prefix='makos-office-') as work:
        os.makedirs(os.path.join(work, 'out'))
        os.makedirs(os.path.join(work, 'home'))
        inner = ['soffice', '-env:UserInstallation=file:///tmp/work/profile', '--headless', '--norestore', '--nolockcheck',
                 '--nodefault', '--nologo', '--convert-to', 'png', '--outdir', '/tmp/work/out', f'/tmp/work/in{ext}']
        if bwrap_works():
            argv = sandbox_argv(inner, work, [(path, f'in{ext}')])
            cwd = None
        else:
            # Fallback without bubblewrap: private copy of the file and a private profile; still time/resource limited.
            shutil.copyfile(path, os.path.join(work, f'in{ext}'))
            inner = ['soffice', f'-env:UserInstallation=file://{work}/profile', '--headless', '--norestore', '--nolockcheck',
                     '--nodefault', '--nologo', '--convert-to', 'png', '--outdir', os.path.join(work, 'out'),
                     os.path.join(work, f'in{ext}')]
            argv, cwd = inner, work
        try:
            run_bounded(argv, TIMEOUT_OFFICE, cwd=cwd, env=_scrubbed_env({'HOME': os.path.join(work, 'home')}), mem=8 * 2 ** 30)
        except TimeoutError:
            return None
        out = os.path.join(work, 'out', f'in.png')
        if os.path.exists(out) and os.path.getsize(out) < 32 * 1024 * 1024:
            return Path(out).read_bytes()
    return None


def pixbuf_thumbnail(path, size=THUMB_PX):
    """GdkPixbuf scaled to fit ``size`` (thread-safe). None if the image cannot be decoded or is huge."""
    from gi.repository import GdkPixbuf
    try:
        if os.path.getsize(path) > IMAGE_LIMIT:
            return None
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(os.fspath(path), size, size, True)
        return pb.apply_embedded_orientation() or pb
    except Exception:
        return None


def image_info(path):
    from gi.repository import GdkPixbuf
    try:
        fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(os.fspath(path))
        if fmt:
            return fmt.get_name().upper(), w, h
    except Exception:
        pass
    return None


# ------------------------------------------------------------- metadata

def office_metadata(path):
    """Title/author/pages from the package metadata of ODF and OOXML files. Bounded XML only."""
    rows = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in ('meta.xml', 'docProps/core.xml', 'docProps/app.xml'):
                try:
                    info = zf.getinfo(name)
                except KeyError:
                    continue
                if info.file_size > 256 * 1024:
                    continue
                text = zf.read(info).decode('utf-8', 'replace')
                for label, tag in [('Title', 'title'), ('Author', 'creator'), ('Author', 'initial-creator'), ('Subject', 'subject'),
                                   ('Pages', 'page-count'), ('Pages', 'Pages'), ('Words', 'word-count'), ('Words', 'Words'),
                                   ('Application', 'generator'), ('Application', 'Application')]:
                    for m in re.finditer(rf'<(?:[\w-]+:)?{tag}[^>]*?(?:\s(?:meta:)?{tag}="([^"]*)")?[^>]*>([^<]*)<', text):
                        value = (m.group(2) or '').strip() or (m.group(1) or '').strip()
                        if value and not any(r[0] == label for r in rows):
                            rows.append((label, value[:200]))
                    m = re.search(rf'<meta:document-statistic[^>]*meta:{tag}="(\d+)"', text)
                    if m and not any(r[0] == label for r in rows):
                        rows.append((label, m.group(1)))
    except (OSError, zipfile.BadZipFile, RuntimeError):
        pass
    return rows


def media_info(path, timeout=6):
    """Duration and stream summary via GStreamer's discoverer; [] when unavailable."""
    try:
        import gi
        gi.require_version('Gst', '1.0')
        gi.require_version('GstPbutils', '1.0')
        from gi.repository import Gst, GstPbutils
        Gst.init(None)
        disc = GstPbutils.Discoverer.new(timeout * Gst.SECOND)
        info = disc.discover_uri(Path(path).absolute().as_uri())
    except Exception:
        return []
    rows = []
    dur = info.get_duration()
    if dur and dur > 0:
        s = int(dur / 1e9)
        rows.append(('Duration', f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}' if s >= 3600 else f'{s // 60}:{s % 60:02d}'))
    for v in info.get_video_streams()[:1]:
        rows.append(('Dimensions', f'{v.get_width()} × {v.get_height()}'))
    for a in info.get_audio_streams()[:1]:
        rows.append(('Audio', f'{a.get_channels()} channels, {a.get_sample_rate()} Hz'))
    tags = info.get_tags()
    if tags:
        for label, tag in (('Title', 'title'), ('Artist', 'artist'), ('Album', 'album')):
            ok, value = tags.get_string(tag)
            if ok and value:
                rows.append((label, value[:120]))
    return rows


def owner_name(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return str(uid)


def group_name(gid):
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except Exception:
        return str(gid)


def metadata_rows(path, deep=True):
    """(label, value) rows for the fallback preview and the preview column."""
    path = os.fspath(path)
    try:
        st = os.lstat(path)
    except OSError as exc:
        return [('Error', model.human_error(exc, os.path.basename(path)))]
    entry = model.stat_entry(path)
    rows = [('Name', entry.name), ('Kind', entry.kind)]
    if not entry.is_dir:
        rows.append(('Size', f'{model.human_size(entry.size)} ({entry.size:,} bytes)' if entry.size >= 1000 else model.human_size(entry.size)))
    rows += [('Where', os.path.dirname(path) or '/'), ('Modified', model.format_date(entry.mtime))]
    if entry.btime:
        rows.append(('Created', model.format_date(entry.btime)))
    if entry.is_symlink:
        rows.append(('Alias to', entry.link_target or '?'))
    kind = classify(path) if deep else 'other'
    if kind == 'image':
        info = image_info(path)
        if info:
            rows.append(('Dimensions', f'{info[1]} × {info[2]} ({info[0]})'))
    elif kind == 'pdf':
        pages = pdf_pages(path) if deep else 0
        if pages:
            rows.append(('Pages', str(pages)))
    elif kind == 'office':
        rows += office_metadata(path)
    elif kind in ('audio', 'video') and deep:
        rows += media_info(path)
    elif kind == 'folder':
        n = model.count_children(path)
        rows.append(('Contains', 'unavailable' if n is None else f'{n} item' + ('' if n == 1 else 's')))
    return rows
