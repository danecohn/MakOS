"""Loopback JSON-RPC control endpoint so Amerika Agent (via amerika-studio-mcp) can drive Render.

Contract: src/os/studio/tools.json (render.* tools). Transport: POST /rpc, `Authorization: Bearer <token>`, JSON-RPC 2.0.
Every method that touches Blender runs on the MAIN thread through Session.main (timer in the UI, pumped in background mode).
"""
import base64
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, prompt, toolspecs

ERR = {'method': -32601, 'params': -32602, 'denied': -32001, 'busy': -32002, 'path': -32003, 'not_ready': -32004, 'other': -32000}


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.data = code, data


def images_field(pngs):
    return [{'mime': 'image/png', 'base64': base64.b64encode(p).decode()} for p in pngs]


class Dispatcher:
    def __init__(self, session):
        self.s = session

    # direct tool use ------------------------------------------------
    def tool(self, name, args, extra=None):
        out = self.s.main.submit(lambda: self.s._tools().call(name, args), timeout=600)
        if not out['ok']:
            raise RpcError(out.get('code', ERR['other']), out['error'])
        res = dict(out['result'])
        if out.get('images'):
            res['images'] = images_field(out['images'])
        if extra:
            res.update(extra)
        return res

    def assistant(self, text, timeout, workflow=None):
        if not self.s.start(text, source='agent', workflow=workflow):
            raise RpcError(ERR['busy'], 'the in-app assistant is busy with another request')
        finished = self.s.done.wait(timeout)
        if not finished:
            self.s.stop()
            self.s.done.wait(10)
            raise RpcError(ERR['other'], f'timeout after {timeout} s (the assistant was stopped; partial work remains in the scene)')
        res = self.s.last_result or {}
        if res.get('error'):
            code = ERR['other']
            raise RpcError(code, res['error'])
        out = {'text': res.get('text', ''), 'stopped': bool(res.get('stopped')),
               'tool_calls': [{'name': c['name'], 'ok': c['ok']} for c in res.get('tool_calls', [])], 'turns': res.get('turns'),
               'usage': res.get('usage')}
        try:
            snap = self.s.main.submit(lambda: self.s._tools().call('viewport_screenshot', {'width': 512, 'height': 384}))
            if snap['ok']:
                out['images'] = images_field(snap['images'])
            info = self.s.main.submit(lambda: self.s._tools().call('scene_info', {'detail': 'summary'}))
            if info['ok']:
                out['scene'] = {'totals': info['result']['totals'], 'selected': info['result']['selected'],
                                'objects': [o['name'] for o in info['result']['objects']][:60]}
        except Exception:
            pass
        return out

    # methods -------------------------------------------------------
    def call(self, method, params, timeout):
        if not isinstance(params, dict):
            raise RpcError(ERR['params'], 'params must be an object')
        name = method[len('render.'):] if method.startswith('render.') else method
        if name == 'app.ping':
            return {'ok': True, 'app': 'render', 'version': config.VERSION, 'ready': True, 'busy': self.s.busy}
        if name in ('scene.info', 'scene_info'):
            return self.tool('scene_info', params or {})
        if name == 'scene.run_python':
            code = params.get('code')
            if not isinstance(code, str) or not code.strip():
                raise RpcError(ERR['params'], 'code is required')
            if len(code) > 100000:
                raise RpcError(ERR['params'], 'code is longer than 100000 characters')
            return self.tool('run_python', {'code': code, 'description': str(params.get('description', ''))[:300]})
        if name in ('viewport.screenshot', 'app.screenshot'):
            args = {}
            for k in ('width', 'height'):
                if k in params:
                    args[k] = max(64, min(1024, int(params[k])))
            view = params.get('view', 'perspective')
            args['view'] = 'perspective' if view == 'current' else view
            if args['view'] not in toolspecs.BY_NAME['viewport_screenshot']['input_schema']['properties']['view']['enum']:
                raise RpcError(ERR['params'], f'unknown view {view}')
            return self.tool('viewport_screenshot', args)
        if name == 'export':
            fmt, path = params.get('format'), params.get('path')
            if fmt not in ('glb', 'gltf', 'fbx', 'obj', 'stl', 'blend', 'png') or not isinstance(path, str):
                raise RpcError(ERR['params'], 'format and path are required (glb|gltf|fbx|obj|stl|blend|png)')
            if fmt == 'png':
                return self.tool('render_preview', {'save_to': path, 'width': 1280, 'height': 960})
            return self.tool('export_file', {'path': path, 'format': fmt, 'selection_only': bool(params.get('selection_only'))})
        if name == 'model.create_from_description':
            d = params.get('description')
            if not isinstance(d, str) or not d.strip():
                raise RpcError(ERR['params'], 'description is required')
            text = prompt.workflow_prompt('describe', d)
            if params.get('style'):
                text += f'\nStyle: {params["style"]}'
            if params.get('name'):
                text += f'\nUse "{params["name"]}" as the base name of the objects and the collection.'
            return self.assistant(text, timeout, 'describe')
        if name == 'model.apply_change':
            ins = params.get('instruction')
            if not isinstance(ins, str) or not ins.strip():
                raise RpcError(ERR['params'], 'instruction is required')
            text = prompt.workflow_prompt('change', ins)
            if params.get('target'):
                text += f'\nTarget: {params["target"]}'
            return self.assistant(text, timeout, 'change')
        if name == 'app.prompt':
            m = params.get('message')
            if not isinstance(m, str) or not m.strip():
                raise RpcError(ERR['params'], 'message is required')
            t = int(params.get('timeout_s', timeout))
            return self.assistant(m, max(5, min(900, t)))
        if name == 'tools.list':
            return {'tools': [{'name': s['name'], 'risk': s['risk']} for s in toolspecs.SPECS]}
        if name.startswith('tool.'):
            tn = name[5:]
            if tn not in toolspecs.BY_NAME:
                raise RpcError(ERR['method'], f'unknown tool {tn}')
            return self.tool(tn, params)
        raise RpcError(ERR['method'], f'unknown method {method}')


class Server:
    def __init__(self, session, token=None, host='127.0.0.1', port=0):
        self.session = session
        self.token = token or secrets.token_urlsafe(32)
        self.dispatcher = Dispatcher(session)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def _send(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                host = (self.headers.get('Host') or '').split(':')[0]
                if host not in ('127.0.0.1', 'localhost', '[::1]') or self.headers.get('Origin'):
                    return self._send(403, {'error': 'forbidden'})
                auth = self.headers.get('Authorization', '')
                if not hmac.compare_digest(auth, 'Bearer ' + outer.token):
                    return self._send(401, {'error': 'unauthorized'})
                if self.path != '/rpc':
                    return self._send(404, {'error': 'not found'})
                try:
                    n = int(self.headers.get('Content-Length', '0'))
                    if n <= 0 or n > 2_000_000:
                        raise ValueError('bad length')
                    req = json.loads(self.rfile.read(n).decode())
                    method, params, rid = req['method'], req.get('params') or {}, req.get('id')
                except Exception:
                    return self._send(400, {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'parse error'}})
                try:
                    timeout = float(self.headers.get('X-Amerika-Timeout') or 600)
                    timeout = max(5.0, min(900.0, timeout))
                except ValueError:
                    timeout = 600.0
                try:
                    result = outer.dispatcher.call(method, params, timeout)
                    self._send(200, {'jsonrpc': '2.0', 'id': rid, 'result': result})
                except RpcError as e:
                    err = {'code': e.code, 'message': str(e)}
                    if e.data is not None:
                        err['data'] = e.data
                    self._send(200, {'jsonrpc': '2.0', 'id': rid, 'error': err})
                except Exception as e:  # noqa: BLE001
                    self._send(200, {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32000, 'message': f'{type(e).__name__}: {e}'}})

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = None
        self.descriptor = None

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}'

    def start(self, descriptor=None):
        self.thread = threading.Thread(target=self.httpd.serve_forever, name='amerika-render-control', daemon=True)
        self.thread.start()
        self.write_descriptor(descriptor)
        return self

    def write_descriptor(self, path=None):
        path = Path(path or config.descriptor_path())
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = json.dumps({'app': 'render', 'url': self.url, 'token': self.token, 'pid': os.getpid(), 'version': config.VERSION})
        tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        self.descriptor = path

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass
        if self.descriptor:
            try:
                data = json.loads(self.descriptor.read_text())
                if data.get('pid') == os.getpid():
                    self.descriptor.unlink()
            except (OSError, ValueError):
                pass
            self.descriptor = None
