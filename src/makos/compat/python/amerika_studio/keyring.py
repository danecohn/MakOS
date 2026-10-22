"""Anthropic key storage in the Secret Service through `secret-tool` (libsecret-tools).

Attributes:  service=amerika-studio  name=anthropic            the shared key
             service=amerika-studio  name=anthropic-<app>      a per-app override (render, engine, sprite, box)
             service=amerika-agent   name=anthropic            Amerika Agent's key (read only, opt-in reuse)

The value only travels over a pipe: `store` writes it to secret-tool's stdin, `lookup` reads stdout. It is never put in
argv, the environment, a file or a log line, and no exception message ever contains it.
"""
import os
import re
import subprocess

from .common import APPS, StudioError

SERVICE = 'amerika-studio'
AGENT_SERVICE = 'amerika-agent'


def secret_tool():
    return os.environ.get('AMERIKA_STUDIO_SECRET_TOOL', 'secret-tool')


def secret_name(app=None):
    if app is None:
        return 'anthropic'
    if app not in APPS:
        raise StudioError(f'unknown app {app!r}', 'bad_app')
    return f'anthropic-{app}'


def _tool(*args, stdin=None):
    try:
        return subprocess.run([secret_tool(), *args], input=stdin, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise StudioError('secret-tool is not installed (package libsecret-tools); the keyring cannot be used.', 'no_secret_tool')
    except subprocess.TimeoutExpired:
        raise StudioError('the keyring did not answer in time (is the login keyring unlocked?)', 'keyring_timeout')


def clean_key(raw):
    """A pasted key: surrounding whitespace removed; embedded whitespace or control characters refused."""
    value = (raw or '').strip()
    if not value:
        raise StudioError('empty value: nothing stored', 'empty_key')
    if re.search(r'[\x00-\x1f\x7f\s]', value):
        raise StudioError('the value contains whitespace or control characters; paste only the key', 'bad_key')
    if len(value) > 4096:
        raise StudioError('the value is unreasonably long', 'bad_key')
    return value


def store(value, app=None):
    value = clean_key(value)
    label = 'Studio: Anthropic API key' + (f' ({app})' if app else '')
    r = _tool('store', f'--label={label}', 'service', SERVICE, 'name', secret_name(app), stdin=value)
    if r.returncode != 0:
        raise StudioError('the keyring refused the value; check that the login keyring is unlocked', 'keyring_refused')


def _lookup(service, name):
    r = _tool('lookup', 'service', service, 'name', name)
    if r.returncode == 0 and r.stdout:
        return r.stdout.rstrip('\n')
    if r.returncode in (0, 1) and not r.stderr.strip():
        return None   # secret-tool exits 1 without output when nothing matches
    raise StudioError('the keyring could not be read; check that the login keyring is unlocked', 'keyring_error')


def lookup(app=None):
    return _lookup(SERVICE, secret_name(app))


def lookup_agent():
    return _lookup(AGENT_SERVICE, 'anthropic')


def _present(fn):
    try:
        return bool(fn())
    except StudioError:
        return False


def present(app=None):
    return _present(lambda: lookup(app))


def agent_present():
    return _present(lookup_agent)


def clear(app=None):
    r = _tool('clear', 'service', SERVICE, 'name', secret_name(app))
    if r.returncode not in (0, 1):
        raise StudioError('the keyring could not remove the value', 'keyring_error')


def resolve(app, settings):
    """The key an app should use: (key, source) with source 'app' | 'shared' | 'agent', or (None, None).

    Order: the app's own override (when stored and not switched off), the shared key, then Amerika Agent's key when the
    user opted in. Keyring errors count as "no key" here; callers that care use lookup() directly.
    """
    if app in APPS and settings.get('override', {}).get(app, True):
        try:
            key = lookup(app)
        except StudioError:
            key = None
        if key:
            return key, 'app'
    try:
        key = lookup()
    except StudioError:
        key = None
    if key:
        return key, 'shared'
    if settings.get('reuse_agent_key'):
        try:
            key = lookup_agent()
        except StudioError:
            key = None
        if key:
            return key, 'agent'
    return None, None


def key_state(settings):
    """{app: bool} for every caller, plus 'shared' and 'agent_available'. Values are presence flags only."""
    state = {}
    shared = present()
    for app in APPS:
        has_override = present(app) and settings.get('override', {}).get(app, True)
        state[app] = bool(has_override or shared or (settings.get('reuse_agent_key') and agent_present()))
    state['agent'] = state['hub'] = bool(shared or (settings.get('reuse_agent_key') and agent_present()))
    return state


def detail(settings):
    """For UIs: which source each app would use, never a value."""
    out = {'shared': present(), 'agent_available': agent_present(), 'apps': {}}
    for app in APPS:
        out['apps'][app] = {'override_stored': present(app), 'override_enabled': settings.get('override', {}).get(app, True)}
    return out
