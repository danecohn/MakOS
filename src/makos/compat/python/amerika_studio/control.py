"""Talking to a running Studio app: descriptor files, JSON-RPC calls, launching through the app's launcher."""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from . import common
from .common import APP_LAUNCHERS, StudioError


class RpcError(StudioError):
    def __init__(self, message, code=-32000, data=None):
        super().__init__(message, 'rpc_error')
        self.rpc_code = code
        self.data = data


def read_descriptor(app, paths=None):
    """The app's control descriptor {app,url,token,pid,version} or None (missing, stale, unsafe)."""
    paths = paths or common.Paths()
    p = paths.descriptor(app)
    try:
        st = p.stat()
        if st.st_uid != os.getuid() or (st.st_mode & 0o077):
            return None            # somebody else could have written or read it: do not trust it
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get('app') != app or not isinstance(d.get('token'), str):
        return None
    u = urllib.parse.urlparse(str(d.get('url', '')))
    if u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost') or not u.port:
        return None                # control endpoints are loopback only
    pid = d.get('pid')
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None            # the app is gone; the file is a leftover
        except PermissionError:
            pass
    return d


def rpc(desc, method, params=None, timeout=60):
    """JSON-RPC 2.0 call. `method` is '<app>.<tool>'. Returns the result; raises RpcError on a JSON-RPC error."""
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}).encode()
    req = urllib.request.Request(desc['url'].rstrip('/') + '/rpc', data=body, method='POST', headers={
        'Authorization': 'Bearer ' + desc['token'], 'Content-Type': 'application/json',
        'X-Amerika-Timeout': str(int(timeout))})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
            msg = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())
        except ValueError:
            raise RpcError(f'the app answered HTTP {e.code}')
        finally:
            e.close()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise RpcError('cannot reach the app: ' + str(getattr(e, 'reason', e)), -32004)
    except ValueError:
        raise RpcError('the app sent an invalid answer')
    if isinstance(msg, dict) and msg.get('error'):
        err = msg['error']
        if not isinstance(err, dict):
            raise RpcError(f'the app refused the request ({err})', -32005)
        raise RpcError(str(err.get('message', 'error')), int(err.get('code', -32000)), err.get('data'))
    return msg.get('result') if isinstance(msg, dict) else None


def ping(app, paths=None):
    """None when not running, else {'ok','ready',...}."""
    d = read_descriptor(app, paths)
    if not d:
        return None
    try:
        out = rpc(d, f'{app}.app.ping', {}, timeout=3)
    except RpcError:
        return None
    return out if isinstance(out, dict) else {'ok': True, 'ready': True}


def installed(app):
    return shutil.which(APP_LAUNCHERS[app]) is not None


def launch(app, wait=45, paths=None, sleep=time.sleep):
    """Start the app through its launcher (if it is not running) and wait until app.ping says ready. Returns the descriptor."""
    if app not in APP_LAUNCHERS:
        raise StudioError(f'unknown app {app!r}', 'bad_app')
    p = ping(app, paths)
    if p and p.get('ready', True):
        return read_descriptor(app, paths)
    if not p:
        exe = shutil.which(APP_LAUNCHERS[app])
        if not exe:
            raise StudioError(f'{common.APP_TITLES[app]} is not installed (launcher {APP_LAUNCHERS[app]} not found). '
                              'Install the amerika-developer package.', 'not_installed')
        try:
            subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as e:
            raise StudioError(f'could not start {common.APP_TITLES[app]}: {e}', 'launch_failed')
    deadline = time.time() + wait
    while time.time() < deadline:
        p = ping(app, paths)
        if p and p.get('ready', True):
            return read_descriptor(app, paths)
        sleep(0.5)
    raise StudioError(f'{common.APP_TITLES[app]} did not become ready within {wait} s', 'launch_timeout')
