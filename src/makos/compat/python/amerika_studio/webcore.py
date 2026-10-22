"""GTK-free logic of amerika-studio-webview: app table, navigation policy, bridge path allowlist, file grants, recent files,
and the loopback JSON-RPC control endpoint. Kept separate so it can be unit-tested without a display."""
import base64
import http.server
import json
import os
import secrets
import socketserver
import threading
import urllib.parse
from pathlib import Path

from . import __version__, common
from .common import StudioError

SPECS = {
    'sprite': {'title': 'Sprite', 'icon': 'amerika-sprite', 'app_id': 'org.amerika.Sprite',
               'filters': [('Sprites and images', ['*.png', '*.gif', '*.aseprite', '*.ase', '*.json', '*.webp']), ('All files', ['*'])],
               'binary': ('.png', '.gif', '.aseprite', '.ase', '.webp', '.jpg', '.jpeg', '.bmp')},
    'box': {'title': 'MakBox', 'icon': 'amerika-box', 'app_id': 'org.amerika.Box',
            'filters': [('Songs', ['*.json', '*.beepbox', '*.wav', '*.mid', '*.midi']), ('All files', ['*'])],
            'binary': ('.wav', '.mid', '.midi', '.ogg', '.mp3', '.flac')},
}
SHARED_WEB = Path(os.environ.get('AMERIKA_STUDIO_WEB', common.SHARE / 'web'))
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_RECENT = 12
BRIDGE_POST = ('/v1/messages',)
BRIDGE_GET = ('/v1/status', '/v1/models')


class RpcFail(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------------------------------------ navigation
def uri_allowed(uri, roots):
    """True for about:blank and for file:// URIs whose real path lies below one of `roots`."""
    if uri == 'about:blank':
        return True
    u = urllib.parse.urlparse(uri or '')
    if u.scheme != 'file' or u.netloc not in ('', 'localhost'):
        return False
    path = os.path.realpath(urllib.parse.unquote(u.path))
    for root in roots:
        r = os.path.realpath(root)
        if path == r or path.startswith(r.rstrip(os.sep) + os.sep):
            return True
    return False


def check_bridge_request(path, body):
    """('GET'|'POST', path) for an allowed call from the page, else raises RpcFail."""
    if not isinstance(path, str):
        raise RpcFail(-32602, 'path must be a string')
    if body is None and path in BRIDGE_GET:
        return 'GET', path
    if path in BRIDGE_POST and isinstance(body, dict):
        return 'POST', path
    raise RpcFail(-32602, f'the page may only call {", ".join(BRIDGE_POST + BRIDGE_GET)} on the bridge')


# ------------------------------------------------------------------------------------------------ files
def is_binary(path, spec):
    return str(path).lower().endswith(tuple(spec['binary']))


def read_for_page(path, binary):
    p = Path(path)
    try:
        size = p.stat().st_size
        if not p.is_file():
            raise RpcFail(-32000, 'not a file')
        if size > MAX_FILE_BYTES:
            raise RpcFail(-32000, 'file too large (limit 64 MiB)')
        raw = p.read_bytes()
    except OSError as e:
        raise RpcFail(-32000, f'cannot read file: {e.strerror}')
    data = base64.b64encode(raw).decode('ascii') if binary else raw.decode('utf-8', 'replace')
    return {'path': str(p), 'name': p.name, 'binary': bool(binary), 'data': data}


def decode_data(data, encoding):
    if not isinstance(data, str):
        raise RpcFail(-32602, 'data must be a string')
    if encoding == 'base64':
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError:
            raise RpcFail(-32602, 'data is not valid base64')
    elif encoding == 'utf8':
        raw = data.encode('utf-8')
    else:
        raise RpcFail(-32602, 'encoding must be utf8 or base64')
    if len(raw) > MAX_FILE_BYTES:
        raise RpcFail(-32000, 'data too large (limit 64 MiB)')
    return raw


class Grants:
    """Paths the page may read again: ones the user picked in a dialog, dropped, or opened from recent, plus the project dir."""

    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.paths = set()

    def grant(self, path):
        self.paths.add(os.path.realpath(path))

    def allowed(self, path):
        real = os.path.realpath(path)
        if real in self.paths:
            return True
        root = os.path.realpath(self.project_dir)
        return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


class Recent:
    def __init__(self, paths, app):
        self.file = paths.recent(app)

    def list(self):
        data = common.read_json(self.file, [])
        out = []
        for p in data if isinstance(data, list) else []:
            if isinstance(p, str) and os.path.isfile(p):
                out.append(p)
        return out[:MAX_RECENT]

    def add(self, path):
        path = os.path.realpath(path)
        items = [path] + [p for p in self.list() if p != path]
        common.ensure_private_dir(self.file.parent)
        common.atomic_write(self.file, json.dumps(items[:MAX_RECENT]), 0o600)
        return items[:MAX_RECENT]

    def clear(self):
        common.ensure_private_dir(self.file.parent)
        common.atomic_write(self.file, '[]', 0o600)


# ------------------------------------------------------------------------------------------------ pending RPCs
class Pending:
    """Hand-over between the control-endpoint thread (waits) and the GTK main loop (answers)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}
        self._n = 0

    def new(self):
        with self._lock:
            self._n += 1
            rid = f'r{self._n}'
            self._items[rid] = {'event': threading.Event(), 'out': None}
            return rid

    def resolve(self, rid, result=None, error=None):
        with self._lock:
            item = self._items.get(rid)
        if item:
            item['out'] = (result, error)
            item['event'].set()

    def wait(self, rid, timeout):
        with self._lock:
            item = self._items.get(rid)
        ok = item['event'].wait(timeout)
        with self._lock:
            self._items.pop(rid, None)
        if not ok:
            raise RpcFail(-32000, 'timeout: the app did not answer in time')
        result, error = item['out']
        if error:
            raise RpcFail(int(error.get('code', -32000)), str(error.get('message', 'error')))
        return result


# ------------------------------------------------------------------------------------------------ control endpoint
class ControlServer:
    """Loopback JSON-RPC 2.0 server + descriptor file $XDG_RUNTIME_DIR/amerika/studio-<app>.json.

    `handler(method, params, timeout)` gets the method WITHOUT the '<app>.' prefix and returns a JSON-able result or raises
    RpcFail. Methods in `direct` (e.g. app.ping) skip the one-call-at-a-time lock.
    """

    def __init__(self, app, handler, paths=None, direct=('app.ping', 'app.open', 'app.screenshot'), version=__version__):
        self.app = app
        self.handler = handler
        self.paths = paths or common.Paths()
        self.direct = set(direct)
        self.version = version
        self.token = secrets.token_urlsafe(32)
        self._busy = threading.Lock()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def _send(self, obj, status=200):
                raw = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                import hmac
                if self.path != '/rpc' or self.headers.get('Origin'):
                    self.close_connection = True
                    return self._send({'error': 'not found'}, 404)
                auth = self.headers.get('Authorization') or ''
                if not hmac.compare_digest(auth.encode(), ('Bearer ' + outer.token).encode()):
                    self.close_connection = True
                    return self._send({'error': 'unauthorized'}, 401)
                try:
                    n = int(self.headers.get('Content-Length', ''))
                    if not 2 <= n <= 32 * 1024 * 1024:
                        raise ValueError
                    req = json.loads(self.rfile.read(n))
                    if not isinstance(req, dict):
                        raise ValueError
                except ValueError:
                    return self._send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'parse error'}})
                self._send(outer.handle(req, self.headers.get('X-Amerika-Timeout')))

        class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        self.httpd = S(('127.0.0.1', 0), H)
        self.port = self.httpd.server_address[1]

    def handle(self, req, timeout_header=None):
        rid = req.get('id')
        method, params = req.get('method'), req.get('params') or {}

        def err(code, message):
            return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': message}}
        prefix = self.app + '.'
        if not isinstance(method, str) or not method.startswith(prefix) or not isinstance(params, dict):
            return err(-32601 if isinstance(method, str) else -32600, 'method not found')
        name = method[len(prefix):]
        try:
            timeout = max(1, min(900, int(timeout_header or 60)))
        except ValueError:
            timeout = 60
        locked = name not in self.direct
        if locked and not self._busy.acquire(blocking=False):
            return err(-32002, 'the app is busy with another request')
        try:
            return {'jsonrpc': '2.0', 'id': rid, 'result': self.handler(name, params, timeout)}
        except RpcFail as e:
            return err(e.code, str(e))
        except StudioError as e:
            return err(getattr(e, 'rpc_code', -32000), str(e))
        except Exception as e:  # noqa: BLE001
            return err(-32000, f'internal error: {type(e).__name__}')
        finally:
            if locked:
                self._busy.release()

    def descriptor(self):
        return {'app': self.app, 'url': f'http://127.0.0.1:{self.port}', 'token': self.token, 'pid': os.getpid(), 'version': self.version}

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name=f'studio-{self.app}-control').start()
        common.ensure_private_dir(self.paths.runtime_dir)
        common.atomic_write(self.paths.descriptor(self.app), json.dumps(self.descriptor()), 0o600)

    def stop(self):
        try:
            d = common.read_json(self.paths.descriptor(self.app), {})
            if d.get('pid') == os.getpid():
                self.paths.descriptor(self.app).unlink()
        except OSError:
            pass
        self.httpd.shutdown()
        self.httpd.server_close()
