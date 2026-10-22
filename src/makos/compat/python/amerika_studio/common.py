"""Paths, constants, settings and small helpers shared by every Studio component.

Nothing in here ever touches a secret; keys live in the Secret Service (see keyring.py).
"""
import json
import os
import re
import tempfile
import time
from pathlib import Path

from . import __version__

APPS = ('render', 'engine', 'sprite', 'box')
APP_TITLES = {'render': 'Render', 'engine': 'Engine', 'sprite': 'Sprite', 'box': 'MakBox'}
APP_LAUNCHERS = {'render': 'amerika-render', 'engine': 'amerika-engine', 'sprite': 'amerika-sprite', 'box': 'amerika-box'}
APP_FOLDERS = {'render': 'Render', 'engine': 'Engine', 'sprite': 'Sprite', 'box': 'Box'}
# callers the bridge accepts in X-Amerika-App (the four apps, Amerika Agent, and the hub itself)
BRIDGE_CALLERS = APPS + ('agent', 'hub')

DEFAULT_MODEL = 'claude-sonnet-5-5'
MODELS = (
    {'id': 'claude-sonnet-5-5', 'name': 'Claude Sonnet 5.5', 'tier': 'balanced', 'note': 'Default: fast and capable'},
    {'id': 'claude-opus-5-5', 'name': 'Claude Opus 5.5', 'tier': 'best', 'note': 'Most capable, slower and costlier'},
    {'id': 'claude-haiku-5-5', 'name': 'Claude Haiku 5.5', 'tier': 'fast', 'note': 'Fastest and cheapest'},
)
MODEL_IDS = tuple(m['id'] for m in MODELS)

ANTHROPIC_VERSION = '2023-06-01'
DEFAULT_UPSTREAM = 'https://api.anthropic.com'
DEFAULT_PORT = 18890
MAX_TOKENS_CAP = 16000
MAX_BODY_BYTES = 12 * 1024 * 1024
DEFAULT_DAILY_BUDGET = 2_000_000        # tokens (input + output) per day; generous, user-adjustable

SHARE = Path(os.environ.get('AMERIKA_STUDIO_SHARE', '/usr/share/amerika-studio'))
DOCS_URL = 'file:///usr/share/doc/amerika-studio/README.md'


def _xdg(env, fallback):
    return Path(os.environ.get(env) or Path.home() / fallback)


class Paths:
    """Per-user locations, resolved when constructed so tests can point HOME / XDG_* elsewhere."""

    def __init__(self):
        self.config_dir = _xdg('XDG_CONFIG_HOME', '.config') / 'amerika-studio'
        self.state_dir = _xdg('XDG_STATE_HOME', '.local/state') / 'amerika-studio'
        self.data_dir = _xdg('XDG_DATA_HOME', '.local/share') / 'amerika-studio'
        runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/tmp/amerika-{os.getuid()}'
        self.runtime_dir = Path(runtime) / 'amerika'
        self.settings = self.config_dir / 'settings.json'
        self.usage = self.state_dir / 'usage.jsonl'
        self.token = self.runtime_dir / 'studio-token'
        self.studio_root = Path(os.environ.get('AMERIKA_STUDIO_ROOT') or Path.home() / 'Studio')

    def descriptor(self, app):
        return self.runtime_dir / f'studio-{app}.json'

    def recent(self, app):
        return self.state_dir / f'recent-{app}.json'

    def project_dir(self, app):
        return self.studio_root / APP_FOLDERS[app]


class StudioError(Exception):
    """Base class. `code` is a short machine-readable string, `status` an HTTP status when relevant."""

    def __init__(self, message, code='error', status=None):
        super().__init__(message)
        self.code = code
        self.status = status


# ------------------------------------------------------------------------------------------------ files
def ensure_private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def atomic_write(path, text, mode=0o600):
    """Write `text` to `path` atomically with the given permission bits (the temp file is never wider than `mode`)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------------------------------------ settings
DEFAULT_SETTINGS = {
    'version': 1,
    'model': DEFAULT_MODEL,
    'daily_budget_tokens': DEFAULT_DAILY_BUDGET,
    'reuse_agent_key': False,                       # fall back to Amerika Agent's Anthropic key when Studio has none
    'override': {a: True for a in APPS},            # use a per-app key when one is stored
    'agent_tools': False,                           # register amerika-studio-mcp with Amerika Agent
    'review_before_run': True,
}


def validate_settings(raw):
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if not isinstance(raw, dict):
        return s
    if raw.get('model') in MODEL_IDS:
        s['model'] = raw['model']
    b = raw.get('daily_budget_tokens')
    if isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 10_000_000_000:
        s['daily_budget_tokens'] = b
    for key in ('reuse_agent_key', 'agent_tools', 'review_before_run'):
        if isinstance(raw.get(key), bool):
            s[key] = raw[key]
    if isinstance(raw.get('override'), dict):
        for a in APPS:
            if isinstance(raw['override'].get(a), bool):
                s['override'][a] = raw['override'][a]
    return s


def load_settings(paths=None):
    paths = paths or Paths()
    return validate_settings(read_json(paths.settings, None))


def save_settings(settings, paths=None):
    paths = paths or Paths()
    settings = validate_settings(settings)
    ensure_private_dir(paths.config_dir)
    atomic_write(paths.settings, json.dumps(settings, indent=2, sort_keys=True) + '\n', 0o600)
    return settings


# ------------------------------------------------------------------------------------------------ misc
APP_RE = re.compile(r'^[a-z]{2,16}$')


def check_app(app, allowed=APPS):
    if app not in allowed:
        raise StudioError(f'unknown app {app!r} (expected one of {", ".join(allowed)})', 'bad_app')
    return app


def today():
    return time.strftime('%Y-%m-%d')


def version():
    return __version__


def tools_json_path():
    for candidate in (SHARE / 'tools.json', Path(__file__).resolve().parent.parent / 'tools.json'):
        if candidate.is_file():
            return candidate
    raise StudioError('tools.json is missing (is amerika-studio installed correctly?)', 'no_tools')


def load_tools():
    return json.loads(tools_json_path().read_text(encoding='utf-8'))
