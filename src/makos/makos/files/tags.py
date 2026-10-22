"""Tags (user.xdg.tags) and comments (user.xdg.comment) in extended attributes.

When a filesystem has no user xattrs the values fall back to a small private JSON
sidecar under the MakOS state directory; user files are never modified in that case.
A path index lets the sidebar list tagged files without crawling the disk.
"""
import errno
import json
import os
import threading
from pathlib import Path

TAG_ATTR = 'user.xdg.tags'
COMMENT_ATTR = 'user.xdg.comment'
MAX_ATTR = 4096

# Standard label colours (original palette). Any other tag uses CUSTOM_COLOUR.
COLOURS = {'Red': '#e0483d', 'Orange': '#ee9a2f', 'Yellow': '#e8c935', 'Green': '#5db84e',
           'Blue': '#3b8de0', 'Purple': '#9a62c9', 'Gray': '#8d949c'}
CUSTOM_COLOUR = '#b0b8c2'
UNSUPPORTED = (errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM, errno.EACCES, errno.ENOSYS, errno.EINVAL)


def colour_of(tag):
    for name, value in COLOURS.items():
        if name.casefold() == tag.casefold():
            return value
    return CUSTOM_COLOUR


def clean_tags(tags):
    seen, out = set(), []
    for raw in tags:
        tag = ' '.join(str(raw).replace(',', ' ').replace('\n', ' ').split())
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


class Sidecar:
    """Fallback store for filesystems without user xattrs."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()

    def _file(self):
        if self.path:
            return self.path
        from .. import common
        return common.STATE / 'files-tags-sidecar.json'

    def read(self):
        try:
            data = json.loads(self._file().read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, attr, path):
        return self.read().get(attr, {}).get(os.path.realpath(path))

    def set(self, attr, path, value):
        with self.lock:
            data = self.read()
            table = data.setdefault(attr, {})
            key = os.path.realpath(path)
            if value:
                table[key] = value
            else:
                table.pop(key, None)
            target = self._file()
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix('.tmp')
            temp.write_text(json.dumps(data))
            temp.replace(target)


class Store:
    def __init__(self, sidecar=None, index_path=None):
        self.sidecar = sidecar or Sidecar()
        self._index_path = Path(index_path) if index_path else None
        self._lock = threading.Lock()

    # -- raw attribute access
    def _get(self, attr, path):
        try:
            return os.getxattr(path, attr, follow_symlinks=False).decode('utf-8', 'replace')
        except OSError as exc:
            if exc.errno in (errno.ENODATA,):
                return ''
            if exc.errno in UNSUPPORTED or exc.errno == errno.ENOENT:
                return self.sidecar.get(attr, path) or '' if exc.errno != errno.ENOENT else ''
            return ''

    def _set(self, attr, path, value):
        data = value.encode('utf-8')[:MAX_ATTR]
        try:
            if data:
                os.setxattr(path, attr, data, follow_symlinks=False)
            else:
                try:
                    os.removexattr(path, attr, follow_symlinks=False)
                except OSError as exc:
                    if exc.errno != errno.ENODATA:
                        raise
        except OSError as exc:
            if exc.errno in UNSUPPORTED:
                self.sidecar.set(attr, path, value)
            else:
                raise

    # -- tags
    def get_tags(self, path):
        raw = self._get(TAG_ATTR, os.fspath(path))
        return clean_tags(raw.split(',')) if raw else []

    def set_tags(self, path, tags):
        path = os.fspath(path)
        tags = clean_tags(tags)
        self._set(TAG_ATTR, path, ','.join(tags))
        self._index_update(path, tags)
        return tags

    def add_tag(self, path, tag):
        return self.set_tags(path, self.get_tags(path) + [tag])

    def remove_tag(self, path, tag):
        return self.set_tags(path, [t for t in self.get_tags(path) if t.casefold() != tag.casefold()])

    def toggle_tag(self, paths, tag):
        """Add the tag to all paths unless every path already has it (then remove). Returns True if added."""
        paths = [os.fspath(p) for p in paths]
        have = [any(t.casefold() == tag.casefold() for t in self.get_tags(p)) for p in paths]
        remove = bool(have) and all(have)
        for path, has in zip(paths, have):
            if remove:
                self.remove_tag(path, tag)
            elif not has:
                self.add_tag(path, tag)
        return not remove

    # -- comments
    def get_comment(self, path):
        return self._get(COMMENT_ATTR, os.fspath(path))

    def set_comment(self, path, text):
        self._set(COMMENT_ATTR, os.fspath(path), text.strip())

    # -- index of tagged paths
    def _index_file(self):
        if self._index_path:
            return self._index_path
        from .. import common
        return common.STATE / 'files-tag-index.json'

    def _index_read(self):
        try:
            data = json.loads(self._index_file().read_text())
            return {k: list(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError, AttributeError):
            return {}

    def _index_update(self, path, tags):
        with self._lock:
            index = self._index_read()
            wanted = {t.casefold() for t in tags}
            changed = False
            for key in list(index):
                if path in index[key] and key.casefold() not in wanted:
                    index[key].remove(path)
                    changed = True
                    if not index[key]:
                        del index[key]
            for tag in tags:
                key = next((k for k in index if k.casefold() == tag.casefold()), tag)
                if path not in index.setdefault(key, []):
                    index[key].append(path)
                    changed = True
            if changed:
                target = self._index_file()
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_suffix('.tmp')
                    temp.write_text(json.dumps(index))
                    temp.replace(target)
                except OSError:
                    pass

    def rename_in_index(self, old, new):
        tags = self.get_tags(new) if os.path.lexists(new) else []
        self._index_update(old, [])
        if tags:
            self._index_update(new, tags)

    def known_tags(self):
        """Tag names with at least one still-tagged file, standard colours first."""
        index = self._index_read()
        names = [n for n in COLOURS] + sorted((k for k in index if k.casefold() not in {c.casefold() for c in COLOURS}),
                                               key=str.casefold)
        return names

    def paths_for(self, tag, limit=5000):
        """Existing paths whose tag list (verified on disk) includes ``tag``."""
        index = self._index_read()
        out = []
        for key, paths in index.items():
            if key.casefold() != tag.casefold():
                continue
            for p in paths:
                if os.path.lexists(p) and any(t.casefold() == tag.casefold() for t in self.get_tags(p)):
                    out.append(p)
                    if len(out) >= limit:
                        return out
        return out


STORE = Store()
