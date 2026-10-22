"""Project-directory confinement: every file path a tool receives is relative to a project root and must stay inside it."""
import os
from pathlib import Path

from .common import StudioError, atomic_write


class ConfineError(StudioError):
    def __init__(self, message):
        super().__init__(message, 'path_outside_project')
        self.rpc_code = -32003


MAX_PATH = 1024


def is_inside(root, path):
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def resolve_in(root, rel, must_exist=False):
    """Absolute path of `rel` below `root`. Rejects absolute paths, '..', NUL bytes, over-long names and symlinks that
    lead out of the root (the target is resolved before the check). Returns a Path."""
    if not isinstance(rel, str) or not rel:
        if rel in ('', '.', None):
            rel = '.'
        else:
            raise ConfineError('path must be a string')
    if '\x00' in rel or len(rel) > MAX_PATH:
        raise ConfineError('invalid path')
    if rel.startswith(('/', '\\', '~')) or (len(rel) > 1 and rel[1] == ':'):
        raise ConfineError('absolute paths are not allowed: use a path relative to the project folder')
    parts = rel.replace('\\', '/').split('/')
    if '..' in parts:
        raise ConfineError('".." is not allowed in project paths')
    root_p = Path(os.path.realpath(root))
    full = root_p.joinpath(*[p for p in parts if p not in ('', '.')])
    if not is_inside(root_p, full):
        raise ConfineError('that path leads outside the project folder')
    if must_exist and not full.exists():
        raise StudioError(f'no such file: {rel}', 'not_found')
    return full


def relative(root, path):
    return Path(os.path.realpath(path)).relative_to(os.path.realpath(root)).as_posix()


HIDDEN_DIRS = ('.git', '.godot', '.import', '__pycache__')


def list_dir(root, rel='.', recursive=False, limit=1000):
    base = resolve_in(root, rel, must_exist=True)
    out = []
    if not base.is_dir():
        raise StudioError('not a folder', 'not_dir')
    it = base.rglob('*') if recursive else base.iterdir()
    for p in sorted(it):
        r = relative(root, p) if is_inside(root, p) else None
        if r is None or any(part in HIDDEN_DIRS for part in Path(r).parts):
            continue
        st = p.lstat()
        out.append({'path': r, 'dir': p.is_dir(), 'size': 0 if p.is_dir() else st.st_size})
        if len(out) >= limit:
            break
    return out


def read_text(root, rel, max_bytes=200000):
    p = resolve_in(root, rel, must_exist=True)
    if not p.is_file():
        raise StudioError('not a file', 'not_file')
    with open(p, 'rb') as fh:
        data = fh.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    return {'path': rel, 'content': data[:max_bytes].decode('utf-8', 'replace'), 'truncated': truncated}


def write_text(root, rel, content, overwrite=False):
    p = resolve_in(root, rel)
    if p == Path(os.path.realpath(root)):
        raise ConfineError('cannot write the project folder itself')
    if p.exists() and not overwrite:
        raise StudioError(f'{rel} exists; pass overwrite=true to replace it', 'exists')
    if p.is_symlink() or p.is_dir():
        raise ConfineError('refusing to write through a link or over a folder')
    p.parent.mkdir(parents=True, exist_ok=True)
    if not is_inside(root, p.parent):
        raise ConfineError('that path leads outside the project folder')
    atomic_write(p, content, 0o644)
    return {'path': rel, 'bytes': len(content.encode('utf-8'))}
