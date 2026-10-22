"""amerika-studio-bridge: loopback proxy between the Studio apps and the Anthropic Messages API.

* Binds 127.0.0.1 only. Every request except GET /v1/ping needs the per-user token (file $XDG_RUNTIME_DIR/amerika/studio-token,
  mode 0600) as `Authorization: Bearer <token>`.
* Adds `x-api-key` and `anthropic-version` server-side. The key and the token are never forwarded to the app, never logged,
  never present in any answer.
* Validates the body (model allowlist, max_tokens cap, size cap, no streaming, known top-level fields only) and enforces a
  daily token budget. The selected key depends on the `X-Amerika-App` header.
* Tests may point the upstream at a fake server with AMERIKA_STUDIO_UPSTREAM; only loopback URLs are honoured so a stray
  variable can never send the key to another host.
"""
import hmac
import http.server
import json
import os
import secrets
import signal
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, common, keyring
from .usage import UsageLog

ALLOWED_FIELDS = {'model', 'max_tokens', 'messages', 'system', 'tools', 'tool_choice', 'temperature', 'top_p', 'top_k',
                  'stop_sequences', 'thinking', 'stream'}
MAX_MESSAGES = 400
MAX_TOOLS = 128
UPSTREAM_TIMEOUT = 600


def upstream_base():
    url = os.environ.get('AMERIKA_STUDIO_UPSTREAM')
    if not url:
        return common.DEFAULT_UPSTREAM
    p = urllib.parse.urlparse(url)
    if p.scheme in ('http', 'https') and p.hostname in ('127.0.0.1', 'localhost', '::1'):
        return url.rstrip('/')
    sys.stderr.write('amerika-studio-bridge: ignoring AMERIKA_STUDIO_UPSTREAM (only loopback URLs are accepted)\n')
    return common.DEFAULT_UPSTREAM


def ensure_token(paths):
    """Return the per-user token, creating the 0600 file when missing or unusable."""
    common.ensure_private_dir(paths.runtime_dir)
    try:
        st = paths.token.stat()
        if st.st_uid == os.getuid() and (st.st_mode & 0o077) == 0:
            tok = paths.token.read_text().strip()
            if len(tok) >= 32:
                return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(32)
    common.atomic_write(paths.token, tok + '\n', 0o600)
    return tok


def error_body(etype, message):
    return {'type': 'error', 'error': {'type': etype, 'message': message}}


def validate_request(body):
    """Return (clean_body, None) or (None, (status, error_type, message))."""
    if not isinstance(body, dict):
        return None, (400, 'invalid_request_error', 'body must be a JSON object')
    extra = sorted(set(body) - ALLOWED_FIELDS)
    if extra:
        return None, (400, 'invalid_request_error', 'field not allowed: ' + ', '.join(str(e)[:40] for e in extra))
    if body.get('stream'):
        return None, (400, 'invalid_request_error', 'streaming is not supported by the Studio bridge (v1)')
    model = body.get('model')
    if model not in common.MODEL_IDS:
        return None, (400, 'invalid_request_error', f'model not allowed: {str(model)[:60]!r}; use one of {", ".join(common.MODEL_IDS)}')
    mt = body.get('max_tokens')
    if isinstance(mt, bool) or not isinstance(mt, int) or mt < 1:
        return None, (400, 'invalid_request_error', 'max_tokens must be a positive integer')
    if mt > common.MAX_TOKENS_CAP:
        return None, (400, 'invalid_request_error', f'max_tokens above the cap of {common.MAX_TOKENS_CAP}')
    msgs = body.get('messages')
    if not isinstance(msgs, list) or not msgs or len(msgs) > MAX_MESSAGES:
        return None, (400, 'invalid_request_error', f'messages must be a list of 1..{MAX_MESSAGES} items')
    if not all(isinstance(m, dict) and m.get('role') in ('user', 'assistant') for m in msgs):
        return None, (400, 'invalid_request_error', 'each message needs a role of user or assistant')
    tools = body.get('tools')
    if tools is not None:
        if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
            return None, (400, 'invalid_request_error', f'tools must be a list of at most {MAX_TOOLS}')
        for t in tools:
            # client tools only: server tools (web search, code execution...) would be work done outside the user's view
            if not isinstance(t, dict) or t.get('type', 'custom') != 'custom' or not isinstance(t.get('name'), str):
                return None, (400, 'invalid_request_error', 'only custom (client) tools are allowed')
    return body, None


class Bridge:
    """State shared by the request threads."""

    def __init__(self, paths=None, token=None):
        self.paths = paths or common.Paths()
        self.token = token or ensure_token(self.paths)
        self.usage = UsageLog(self.paths)
        self.upstream = upstream_base()
        self._slots = threading.BoundedSemaphore(8)
        self._key_cache = {}
        self._key_lock = threading.Lock()
        self.started = time.time()

    def settings(self):
        return common.load_settings(self.paths)

    def key_for(self, app):
        """(key, source) with a 5 second cache so a burst of calls does not hit the keyring every time."""
        now = time.time()
        with self._key_lock:
            hit = self._key_cache.get(app)
            if hit and now - hit[0] < 5:
                return hit[1]
        val = keyring.resolve(app, self.settings())
        if val[0]:       # a missing key is never cached: saving one must work immediately
            with self._key_lock:
                self._key_cache[app] = (now, val)
        return val

    def status(self):
        s = self.settings()
        return {'key': keyring.key_state(s), 'models': list(common.MODEL_IDS), 'default_model': s['model'],
                'version': __version__,
                'budget': {'daily_tokens': s['daily_budget_tokens'], 'used_today': self.usage.tokens_today()}}

    def forward(self, app, body):
        """Send a validated body upstream. Returns (status, json_body, extra_headers)."""
        s = self.settings()
        budget = s['daily_budget_tokens']
        if budget and self.usage.tokens_today() >= budget:
            return 429, error_body('budget_exceeded', f'The daily Studio token budget ({budget:,}) is used up. '
                                   'Raise it in Studio or wait until tomorrow.'), {}
        key, _src = self.key_for(app)
        if not key:
            return 403, error_body('no_api_key', 'No Anthropic key is set for Studio.'), {}
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(self.upstream + '/v1/messages', data=data, method='POST', headers={
            'x-api-key': key, 'anthropic-version': common.ANTHROPIC_VERSION, 'content-type': 'application/json',
            'user-agent': f'amerika-studio-bridge/{__version__}'})
        status, raw, headers = 502, b'', {}
        with self._slots:
            try:
                with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as resp:
                    status, raw = resp.status, resp.read()
                    if resp.headers.get('request-id'):
                        headers['request-id'] = resp.headers.get('request-id')
            except urllib.error.HTTPError as e:
                status, raw = e.code, e.read()
                for h in ('retry-after', 'request-id'):
                    if e.headers.get(h):
                        headers[h] = e.headers.get(h)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                reason = getattr(e, 'reason', e)
                return 502, error_body('bridge_upstream_unreachable', f'Cannot reach the Anthropic API: {type(reason).__name__}'), {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return 502, error_body('bridge_upstream_invalid', f'The upstream answer was not JSON (status {status}).'), headers
        if status == 200 and isinstance(parsed, dict):
            u = parsed.get('usage') or {}
            self.usage.record(app, body.get('model'), u.get('input_tokens', 0), u.get('output_tokens', 0))
        elif status >= 400 and not (isinstance(parsed, dict) and isinstance(parsed.get('error'), dict)):
            parsed = error_body('api_error', f'upstream status {status}')
        return status, parsed, headers


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'amerika-studio-bridge'
    protocol_version = 'HTTP/1.1'
    bridge = None   # set on the subclass created by make_server

    def log_message(self, fmt, *args):
        pass   # never log request lines; _log writes our own one-liner (method, path, status, app)

    def _log(self, status, ms, app):
        sys.stderr.write(f'{self.command} {self.path.split("?")[0][:60]} {status} {ms}ms app={app}\n')

    def _send(self, status, obj, headers=None):
        data = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        if host not in ('127.0.0.1', 'localhost', '[::1]'):
            return False, 'bad host'          # DNS rebinding guard
        if self.headers.get('Origin'):
            return False, 'browser origins are not allowed'
        auth = self.headers.get('Authorization') or ''
        tok = auth[7:] if auth.lower().startswith('bearer ') else (self.headers.get('X-Amerika-Token') or '')
        if not tok or not hmac.compare_digest(tok.encode(), self.bridge.token.encode()):
            return False, 'bad token'
        return True, ''

    def _app(self):
        app = (self.headers.get('X-Amerika-App') or 'hub').strip().lower()
        return app if app in common.BRIDGE_CALLERS else None

    def _deny(self, why):
        time.sleep(0.2)
        self.close_connection = True
        self._send(401, error_body('bridge_auth_error', why))
        self._log(401, 0, '-')

    def do_GET(self):
        t0 = time.time()
        path = self.path.split('?')[0]
        if path == '/v1/ping':
            self._send(200, {'ok': True, 'service': 'amerika-studio-bridge', 'version': __version__})
            return
        ok, why = self._authorized()
        if not ok:
            return self._deny(why)
        if path == '/v1/status':
            self._send(200, self.bridge.status())
        elif path == '/v1/models':
            self._send(200, {'default': self.bridge.settings()['model'], 'models': list(common.MODELS)})
        else:
            self._send(404, error_body('not_found_error', 'unknown path'))
        self._log(200, int((time.time() - t0) * 1000), self._app())

    def do_POST(self):
        t0 = time.time()
        path = self.path.split('?')[0]
        ok, why = self._authorized()
        if not ok:
            return self._deny(why)
        if path != '/v1/messages':
            self.close_connection = True
            return self._send(404, error_body('not_found_error', 'unknown path'))
        app = self._app()
        if app is None:
            self.close_connection = True
            return self._send(400, error_body('invalid_request_error', 'unknown X-Amerika-App'))
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            self.close_connection = True
            return self._send(411, error_body('invalid_request_error', 'Content-Length required'))
        if length < 2 or length > common.MAX_BODY_BYTES:
            self.close_connection = True
            return self._send(413, error_body('request_too_large', f'body must be 2..{common.MAX_BODY_BYTES} bytes'))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except ValueError:
            return self._send(400, error_body('invalid_request_error', 'body is not valid JSON'))
        clean, bad = validate_request(body)
        if bad:
            self._send(bad[0], error_body(bad[1], bad[2]))
            self._log(bad[0], int((time.time() - t0) * 1000), app)
            return
        status, parsed, headers = self.bridge.forward(app, clean)
        self._send(status, parsed, headers)
        self._log(status, int((time.time() - t0) * 1000), app)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(bridge, port=None):
    port = common.DEFAULT_PORT if port is None else port
    handler = type('BoundHandler', (Handler,), {'bridge': bridge})
    return Server(('127.0.0.1', port), handler)


def main(argv=None):
    paths = common.Paths()
    port = int(os.environ.get('AMERIKA_STUDIO_PORT', common.DEFAULT_PORT))
    bridge = Bridge(paths)
    try:
        server = make_server(bridge, port)
    except OSError as e:
        sys.stderr.write(f'amerika-studio-bridge: cannot listen on 127.0.0.1:{port}: {e}\n')
        return 1
    sys.stderr.write(f'amerika-studio-bridge {__version__} listening on 127.0.0.1:{server.server_address[1]}\n')
    pidfile = paths.runtime_dir / 'studio-bridge.pid'
    common.atomic_write(pidfile, f'{os.getpid()}\n', 0o600)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if pidfile.read_text().strip() == str(os.getpid()):
                pidfile.unlink()
        except OSError:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
