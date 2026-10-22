"""Paths and endpoints. Pure Python (usable from tests and from Blender)."""
import json
import os
from pathlib import Path

VERSION = '3.1.1'
APP = 'render'
DEFAULT_MODEL = 'claude-sonnet-5-5'
MODELS = ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5']
BRIDGE_DEFAULT = 'http://127.0.0.1:18890'
NOTICE = ('Render is powered by Blender (GPL-3.0-or-later). Blender is a trademark of the Blender Foundation; '
          'Render is not affiliated with or endorsed by the Blender Foundation.')


def runtime_dir():
    base = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    return Path(base) / 'amerika'


def token_path():
    return runtime_dir() / 'studio-token'


def descriptor_path():
    return runtime_dir() / 'studio-render.json'


def bridge_url():
    url = os.environ.get('AMERIKA_STUDIO_BRIDGE', BRIDGE_DEFAULT).rstrip('/')
    # Only the local bridge is ever allowed.
    if not (url.startswith('http://127.0.0.1:') or url.startswith('http://localhost:') or url.startswith('http://[::1]:')):
        raise RuntimeError('Render only talks to the local Studio bridge on 127.0.0.1')
    return url


def read_token():
    try:
        return token_path().read_text().strip()
    except OSError:
        return ''


PROJECT_OVERRIDE = ''


def project_dir():
    p = PROJECT_OVERRIDE or os.environ.get('AMERIKA_RENDER_PROJECT')
    path = Path(p).expanduser() if p else Path.home() / 'Studio' / 'Render'
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def state_dir():
    base = os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local/state')
    d = Path(base) / 'amerika-render'
    d.mkdir(parents=True, exist_ok=True)
    return d


def confine(rel, root=None, must_exist=False):
    """Resolve `rel` inside the project dir. Raises PathError if it escapes (.. , absolute elsewhere, symlinks)."""
    root = Path(root or project_dir()).resolve()
    if not isinstance(rel, str) or not rel or '\x00' in rel:
        raise PathError('path must be a non-empty string')
    p = Path(rel).expanduser()
    full = p if p.is_absolute() else root / p
    # resolve symlinks of the deepest existing parent so a symlink cannot hop out
    resolved = full.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise PathError(f'path "{rel}" is outside the project directory {root}') from None
    if must_exist and not resolved.exists():
        raise PathError(f'file "{rel}" does not exist in the project directory')
    return resolved


class PathError(ValueError):
    pass
