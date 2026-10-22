"""Seek's query engine: no GTK. `fast()` is cheap and runs on the main thread; `slow()` (file search, contacts, recents,
dictionary) must run on a worker thread. `grouped()` orders results for display."""
import os
from pathlib import Path

from .. import common
from . import index as indexmod
from . import providers as P

PER_GROUP = {'Applications': 6, 'System Settings': 4, 'Contacts': 4, 'Files': 8, 'Recent': 4, 'Dictionary': 1, 'Web': 1, 'Calculator': 1, 'Conversion': 1}


class Engine:
    def __init__(self, home=None, apps=None, db=None, settings=None):
        self.home = Path(home or Path.home())
        self.apps = apps
        self._db = db
        self._index = None
        self._people = None
        self.settings = settings if settings is not None else common.load_settings()
        self.exclusions = list(self.settings.get('seek_exclusions', []))

    # ---- lazy resources
    def index(self):
        if self._index is None:
            path = self._db or indexmod.db_path()
            if self._db is None and not Path(path).exists():
                return None  # the background indexer has not created it yet
            try:
                self._index = indexmod.Index(path)
            except Exception:  # noqa: BLE001 - a damaged index must never break search
                self._index = None
        return self._index

    def close(self):
        if self._index is not None:
            self._index.close()
            self._index = None

    def people(self):
        if self._people is None:
            self._people = P.load_contacts(self.home)
        return self._people

    def status(self):
        idx = self.index()
        return {'files': 'LocalSearch' if P.localsearch_working() else ('index' if idx else 'basic'),
                'indexed': idx.count() if idx else 0,
                'dictionary': P.dictionary_backend(),
                'contacts': bool(sum(len(x) for x in P.contact_sources(self.home)))}

    # ---- queries
    def fast(self, text, applications_only=False):
        text = text.strip()
        if not text:
            return []
        out = P.applications(text, self.apps)
        if applications_only:
            return out
        out = P.calculator(text) + P.conversion(text) + out + P.settings_panes(text)
        return out

    def slow(self, text):
        text = text.strip()
        if len(text) < 2:
            return []
        out = []
        roots = [r for r in indexmod.default_roots(self.home) if r.is_dir()]
        files = []
        if P.FILTER_WORDS.search(text):  # kind:image tag:Red ext:pdf are understood by the Files package's search
            files = P.files_api(text, roots)
        if not files:
            files = P.localsearch(text, self.home, self.exclusions)
        if not files:
            idx = self.index()
            if idx and idx.count():
                files = P.indexed_files(text, idx)
            else:
                files = P.files_api(text, roots) or P.walk_fallback(text, self.home)
        out += files
        out += P.contacts(text, self.people())
        out += P.recent_files(text)
        out += P.dictionary(text)
        return out

    def web(self, text):
        return P.web(text, self.settings.get('seek_web_engine', 'duckduckgo'))

    def recents(self):
        return P.recent_files('', 6)


def grouped(results):
    """[(group, [Result])] in display order, capped per group, duplicates (same action) removed."""
    seen, buckets = set(), {g: [] for g in P.GROUPS}
    for r in sorted(results, key=lambda r: -r.score):
        key = (r.group, r.action)
        if key in seen or r.group not in buckets:
            continue
        seen.add(key)
        if len(buckets[r.group]) < PER_GROUP.get(r.group, 5):
            buckets[r.group].append(r)
    return [(g, buckets[g]) for g in P.GROUPS if buckets[g]]
