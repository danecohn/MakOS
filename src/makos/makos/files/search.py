"""Files search API. Seek (makos.search) and the Files window both call this module.

    from makos.files import search as files_search
    hits = files_search.search('report', roots=[Path.home()], limit=30)
    handle = files_search.search_async('report', on_hit, on_done)   # streamed from a worker thread; handle.cancel()

Queries are space separated words that must all appear in the name. Optional filters: ``kind:image``
(folder, image, audio, video, pdf, document, text, archive, code), ``tag:Red``, ``ext:txt``. With
``contents=True`` text files up to 2 MB are also scanned (first 256 KB). Searches are bounded in
directories visited and time, skip hidden folders, and never follow symlinked folders.
"""
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import model, tags

MAX_DIRS = 60000
MAX_SECONDS = 25.0
SKIP_ROOTS = ('/proc', '/sys', '/dev', '/run', '/snap', '/var/lib', '/var/cache')
KIND_MATCH = {
    'folder': lambda e: e.is_dir, 'image': lambda e: e.icon == 'file-image', 'audio': lambda e: e.icon == 'file-audio',
    'video': lambda e: e.icon == 'file-video', 'pdf': lambda e: e.icon == 'file-pdf',
    'document': lambda e: e.icon in ('file-document', 'file-pdf', 'file-spreadsheet', 'file-presentation', 'file-text'),
    'text': lambda e: e.icon in ('file-text', 'file-code'), 'archive': lambda e: e.icon == 'file-archive',
    'code': lambda e: e.icon == 'file-code',
}


@dataclass
class SearchHit:
    path: str
    name: str
    kind: str
    mtime: float
    size: int
    score: int
    is_dir: bool
    where: str
    icon: str = 'file-generic'
    snippet: str = ''

    def entry(self):
        e = model.stat_entry(self.path)
        e.where = self.where
        return e


def parse_query(text):
    words, kinds, tag_names, exts = [], set(), [], set()
    for token in text.split():
        low = token.casefold()
        if low.startswith('kind:') and len(low) > 5:
            kinds.add(low[5:])
        elif low.startswith('tag:') and len(low) > 4:
            tag_names.append(token[4:])
        elif low.startswith('ext:') and len(low) > 4:
            exts.add('.' + low[4:].lstrip('.'))
        else:
            words.append(low)
    return words, kinds, tag_names, exts


def _score(name_low, words):
    total = 0
    for w in words:
        if name_low == w:
            total += 100
        elif name_low.startswith(w):
            total += 80
        elif any(part.startswith(w) for part in name_low.replace('_', ' ').replace('-', ' ').replace('.', ' ').split()):
            total += 60
        elif w in name_low:
            total += 40
        else:
            return 0
    return total // max(1, len(words))


def _text_hit(path, size, needle):
    if size > 2_000_000:
        return None
    try:
        with open(path, 'rb') as stream:
            head = stream.read(262144)
    except OSError:
        return None
    if b'\0' in head[:4096]:
        return None
    text = head.decode('utf-8', 'ignore')
    i = text.casefold().find(needle)
    if i < 0:
        return None
    start = max(0, i - 40)
    return ' '.join(text[start:i + len(needle) + 60].split())


def iter_search(query, roots=None, kinds=None, contents=False, cancel=None, show_hidden=False,
                max_dirs=MAX_DIRS, max_seconds=MAX_SECONDS):
    words, qkinds, qtags, qexts = parse_query(query)
    kinds = set(kinds or ()) | qkinds
    if not words and not (kinds or qtags or qexts):
        return
    if words and len(' '.join(words)) < 2 and not (kinds or qtags or qexts):
        return
    roots = [Path(r) for r in (roots or [Path.home()])]
    deadline = time.monotonic() + max_seconds
    visited = 0
    needle = ' '.join(words) if contents else ''
    seen_dirs = set()
    for root in roots:
        stack = [str(root)]
        while stack:
            if cancel is not None and cancel.is_set():
                return
            if visited >= max_dirs or time.monotonic() > deadline:
                return
            current = stack.pop()
            visited += 1
            try:
                st = os.stat(current)
                key = (st.st_dev, st.st_ino)
                if key in seen_dirs:
                    continue
                seen_dirs.add(key)
                scan = os.scandir(current)
            except OSError:
                continue
            with scan:
                subdirs = []
                for child in scan:
                    name = child.name
                    if name.startswith('.') and not show_hidden:
                        continue
                    try:
                        st = child.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    import stat as statmod
                    is_dir = statmod.S_ISDIR(st.st_mode)
                    if is_dir and not child.path.startswith(SKIP_ROOTS):
                        subdirs.append(child.path)
                    elif statmod.S_ISLNK(st.st_mode):
                        pass
                    low = name.casefold()
                    score = _score(low, words) if words else 50
                    snippet = ''
                    if words and not score and contents and not is_dir and statmod.S_ISREG(st.st_mode):
                        mime = model.content_type(name)
                        if mime.startswith('text/') or mime in ('application/json', 'application/xml', 'application/x-shellscript'):
                            hit_text = _text_hit(child.path, st.st_size, needle)
                            if hit_text:
                                score, snippet = 20, hit_text
                    if not score:
                        continue
                    entry = model.entry_from_stat(name, child.path, st, False, '', None, current) if not statmod.S_ISLNK(st.st_mode) \
                        else model.stat_entry(child.path)
                    if kinds and not any(KIND_MATCH.get(k, lambda e: False)(entry) for k in kinds):
                        continue
                    if qexts and os.path.splitext(name)[1].lower() not in qexts:
                        continue
                    if qtags:
                        have = {t.casefold() for t in tags.STORE.get_tags(child.path)}
                        if not all(t.casefold() in have for t in qtags):
                            continue
                    yield SearchHit(child.path, name, entry.kind, entry.mtime, entry.size, score, entry.is_dir, current,
                                    entry.icon, snippet)
                stack.extend(reversed(sorted(subdirs)))


def search(query, roots=None, limit=100, kinds=None, contents=False, cancel=None, show_hidden=False, **bounds):
    """Return up to ``limit`` hits, best first (score, then most recently modified)."""
    hits = []
    for hit in iter_search(query, roots, kinds, contents, cancel, show_hidden, **bounds):
        hits.append(hit)
        if len(hits) >= limit * 4:       # gather a window, then rank
            break
    hits.sort(key=lambda h: (-h.score, -h.mtime, h.name.casefold()))
    return hits[:limit]


class Handle:
    def __init__(self):
        self.stop = threading.Event()
        self.thread = None

    def cancel(self):
        self.stop.set()

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout)


def search_async(query, on_hit, on_done=None, roots=None, limit=500, dispatch=None, **kw):
    """Stream hits from a worker thread. ``dispatch`` (e.g. GLib.idle_add wrapper) marshals callbacks."""
    handle = Handle()
    deliver = dispatch or (lambda fn: fn())

    def run():
        count = 0
        try:
            for hit in iter_search(query, roots, cancel=handle.stop, **kw):
                if handle.stop.is_set():
                    break
                deliver(lambda h=hit: on_hit(h) if not handle.stop.is_set() else None)
                count += 1
                if count >= limit:
                    break
        finally:
            if on_done:
                deliver(on_done)
    handle.thread = threading.Thread(target=run, daemon=True, name='makos-files-search')
    handle.thread.start()
    return handle
