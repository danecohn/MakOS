"""Command runner shared by the settings backends.

Every backend goes through `run()` so tests (and the screenshot rig) can swap in a fake with `set_runner()`.
Arguments are always fixed argument lists, never a shell string. `input` is for secrets: it goes to the
child's stdin and is never logged, echoed or placed in argv.
"""
import os
import shutil
import subprocess
from collections import namedtuple
from pathlib import Path

Result = namedtuple('Result', 'code out err')


def _real(argv, timeout=5, input=None, env=None):  # noqa: A002 - mirrors subprocess
    full_env = dict(os.environ)
    full_env.pop('LD_PRELOAD', None)  # the shell's layer-shell preload must not reach children
    full_env.update(env or {})
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input, env=full_env)
        return Result(done.returncode, done.stdout.strip(), done.stderr.strip())
    except (OSError, subprocess.TimeoutExpired) as error:
        return Result(127, '', str(error))


_runner = _real
_which = shutil.which


def set_runner(fn, which=None):
    """Install a fake runner (tests, rig fixtures). `which` optionally fakes tool discovery."""
    global _runner, _which
    _runner = fn or _real
    _which = which or shutil.which


def run(argv, timeout=5, input=None, env=None):  # noqa: A002
    res = _runner(list(argv), timeout=timeout, input=input, env=env)
    return res if isinstance(res, Result) else Result(*res)


def have(tool):
    return bool(_which(tool))


def popen(argv):
    """Fire-and-forget launch of a GUI helper (never inherits the shell's LD_PRELOAD)."""
    env = dict(os.environ)
    env.pop('LD_PRELOAD', None)
    try:
        return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env)
    except OSError:
        return None


# ---------------------------------------------------------------- KDE config (kreadconfig6 / kwriteconfig6)
def kread(file, group, key, default=''):
    argv = ['kreadconfig6', '--file', file]
    for g in group.split(']['):
        argv += ['--group', g]
    res = run(argv + ['--key', key, '--default', default])
    return res.out if res.code == 0 else default


def kwrite(file, group, key, value):
    argv = ['kwriteconfig6', '--file', file]
    for g in group.split(']['):
        argv += ['--group', g]
    value = str(value).lower() if isinstance(value, bool) else str(value)
    return run(argv + ['--key', key, value], timeout=10).code == 0


def kwin_reconfigure():
    run(['busctl', '--user', 'call', 'org.kde.KWin', '/KWin', 'org.kde.KWin', 'reconfigure'], timeout=10)


def gsettings_set(schema, key, value):
    if not have('gsettings'):
        return False
    return run(['gsettings', 'set', schema, key, str(value)]).code == 0


def gsettings_get(schema, key, default=''):
    res = run(['gsettings', 'get', schema, key])
    return res.out if res.code == 0 else default


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')


def data_home():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')


def parse_kv(text, sep='='):
    out = {}
    for line in text.splitlines():
        if sep in line:
            k, v = line.split(sep, 1)
            out[k.strip()] = v.strip()
    return out


def split_nmcli(line):
    """Split one `nmcli -t` line on unescaped colons (nmcli escapes ':' and '\\' with a backslash)."""
    fields, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == '\\' and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ':':
            fields.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    fields.append(''.join(cur))
    return fields

