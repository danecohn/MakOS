"""Anthropic client helper for Studio apps: talks to the local bridge (never to Anthropic directly) and runs the
tool-use loop. Non-streaming (v1).

The apps call `run_loop()` with their own tool handlers, so tools execute inside Blender / Godot / the webview. The
bridge adds the API key; this module only ever holds the bridge token.
"""
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request

from . import common
from .common import StudioError

RETRY_STATUSES = (429, 529, 502, 503)
DEFAULT_RETRIES = 4
MAX_TOOL_RESULT_CHARS = 60000


class ApiError(StudioError):
    """Mapped error with a user-presentable `message`. `kind` is one of: bridge_down, bridge_auth, no_key, key_rejected,
    budget, rate_limit, overloaded, invalid_request, too_large, server, network, stopped."""

    def __init__(self, message, kind, status=None, retry_after=None):
        super().__init__(message, kind, status)
        self.kind = kind
        self.retry_after = retry_after


def map_error(status, body, retry_after=None):
    """Turn a bridge/upstream error answer into an ApiError."""
    err = body.get('error', {}) if isinstance(body, dict) else {}
    etype, msg = err.get('type', ''), err.get('message', '') or 'request failed'
    if etype == 'bridge_auth_error':
        return ApiError('The Studio bridge refused this app (bad token). Run "amerika-studio ensure" or restart the bridge.', 'bridge_auth', status)
    if etype == 'no_api_key':
        return ApiError('No Anthropic key is set. Open Studio and choose "Set up Anthropic key".', 'no_key', status)
    if etype == 'budget_exceeded':
        return ApiError(msg, 'budget', status)
    if status == 401 or etype == 'authentication_error':
        return ApiError('Anthropic rejected the key. Check it in Studio > Set up Anthropic key.', 'key_rejected', status)
    if status == 403 or etype == 'permission_error':
        return ApiError('Anthropic denied this request: ' + msg, 'key_rejected', status)
    if status == 413 or etype == 'request_too_large':
        return ApiError('The request was too large (many or big images?). ' + msg, 'too_large', status)
    if status == 429 or etype == 'rate_limit_error':
        return ApiError('Rate limited by Anthropic; try again in a moment.', 'rate_limit', status, retry_after)
    if status == 529 or etype == 'overloaded_error':
        return ApiError('Anthropic is overloaded right now; try again shortly.', 'overloaded', status, retry_after)
    if status == 400 or etype == 'invalid_request_error':
        return ApiError('Invalid request: ' + msg, 'invalid_request', status)
    return ApiError(f'Upstream error ({status}): {msg}', 'server', status, retry_after)


class BridgeClient:
    def __init__(self, app, base_url=None, token=None, paths=None, sleep=time.sleep, retries=DEFAULT_RETRIES, timeout=300):
        self.app = app
        self.paths = paths or common.Paths()
        port = int(os.environ.get('AMERIKA_STUDIO_PORT', common.DEFAULT_PORT))
        self.base_url = (base_url or f'http://127.0.0.1:{port}').rstrip('/')
        self._token = token
        self.sleep = sleep
        self.retries = retries
        self.timeout = timeout

    def token(self):
        if self._token:
            return self._token
        try:
            return self.paths.token.read_text().strip()
        except OSError:
            raise ApiError('The Studio bridge is not running (no token file). Run "amerika-studio ensure".', 'bridge_down')

    def _request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers={
            'Authorization': 'Bearer ' + self.token(), 'Content-Type': 'application/json', 'X-Amerika-App': self.app})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read() or b'{}'), None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = {'error': {'type': 'unknown', 'message': raw[:200].decode('utf-8', 'replace')}}
            ra = e.headers.get('retry-after')
            return e.code, body, float(ra) if ra and ra.replace('.', '', 1).isdigit() else None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ApiError('Cannot reach the Studio bridge: ' + str(getattr(e, 'reason', e)), 'bridge_down')

    def get(self, path):
        status, body, ra = self._request('GET', path)
        if status >= 400:
            raise map_error(status, body, ra)
        return body

    def status(self):
        return self.get('/v1/status')

    def messages(self, payload, stop=None):
        """POST /v1/messages with retries on 429/529 (and 502/503), exponential backoff with jitter. Returns the response dict."""
        attempt = 0
        while True:
            if stop is not None and stop.is_set():
                raise ApiError('Stopped.', 'stopped')
            status, body, ra = self._request('POST', '/v1/messages', payload)
            if status < 400:
                return body
            err = map_error(status, body, ra)
            if status in RETRY_STATUSES and err.kind not in ('budget', 'bridge_auth', 'no_key') and attempt < self.retries:
                delay = ra if ra else min(30, 2 ** attempt) * (0.75 + random.random() / 2)
                attempt += 1
                self.sleep(min(delay, 60))
                continue
            raise err


# ------------------------------------------------------------------------------------------------ tool results
def _result_blocks(result):
    """Convert a tool handler's return value into Messages-API tool_result `content`.

    str -> text; dict/list -> JSON text; dict with 'image' {mime, base64} (or 'images') -> image blocks (+ remaining JSON).
    """
    blocks = []
    if isinstance(result, dict) and ('image' in result or 'images' in result):
        rest = dict(result)
        images = rest.pop('images', None) or []
        if 'image' in rest:
            images = [rest.pop('image')] + list(images)
        for img in images:
            if isinstance(img, dict) and img.get('base64'):
                blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': img.get('mime', 'image/png'), 'data': img['base64']}})
        if rest:
            blocks.insert(0, {'type': 'text', 'text': json.dumps(rest, ensure_ascii=False)[:MAX_TOOL_RESULT_CHARS]})
        return blocks or [{'type': 'text', 'text': 'ok'}]
    if isinstance(result, str):
        text = result
    elif result is None:
        text = 'ok'
    else:
        text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + '\n[truncated]'
    return [{'type': 'text', 'text': text}]


class LoopResult:
    def __init__(self):
        self.text = ''
        self.messages = []
        self.tool_calls = []        # [{name, input, ok, summary}]
        self.usage = {'input_tokens': 0, 'output_tokens': 0}
        self.stop_reason = None
        self.turns = 0
        self.stopped = False
        self.hit_max_turns = False

    def as_dict(self):
        return {'text': self.text, 'tool_calls': self.tool_calls, 'usage': self.usage, 'stop_reason': self.stop_reason,
                'turns': self.turns, 'stopped': self.stopped, 'hit_max_turns': self.hit_max_turns}


def text_of(content):
    return ''.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')


def run_loop(client, *, messages, tools=None, handler=None, system=None, model=None, max_tokens=4096, max_turns=12,
             stop=None, on_event=None, extra=None):
    """Run the tool-use loop until the model stops asking for tools.

    messages   conversation so far (list of Messages-API dicts); a copy is extended and returned in the result
    tools      Messages-API tool definitions
    handler    callable(name, input, tool_use_id) -> result (str | dict | None | with image(s)); exceptions become is_error
               results so the model can recover
    stop       threading.Event; when set, the loop ends after the current step and every pending tool_use gets an error result
    on_event   callable(kind, data) with kind in 'request', 'text', 'tool_use', 'tool_result', 'usage' (UI progress)
    """
    emit = on_event or (lambda kind, data: None)
    res = LoopResult()
    res.messages = [dict(m) for m in messages]
    stop = stop or threading.Event()
    model = model or common.load_settings().get('model', common.DEFAULT_MODEL)
    for turn in range(max_turns):
        if stop.is_set():
            res.stopped = True
            break
        payload = {'model': model, 'max_tokens': max_tokens, 'messages': res.messages}
        if system:
            payload['system'] = system
        if tools:
            payload['tools'] = tools
        if extra:
            payload.update(extra)
        emit('request', {'turn': turn + 1})
        resp = client.messages(payload, stop=stop)
        res.turns += 1
        u = resp.get('usage') or {}
        res.usage['input_tokens'] += int(u.get('input_tokens', 0) or 0)
        res.usage['output_tokens'] += int(u.get('output_tokens', 0) or 0)
        emit('usage', dict(res.usage))
        content = resp.get('content') or []
        res.messages.append({'role': 'assistant', 'content': content})
        res.stop_reason = resp.get('stop_reason')
        chunk = text_of(content)
        if chunk:
            res.text = chunk
            emit('text', chunk)
        uses = [b for b in content if isinstance(b, dict) and b.get('type') == 'tool_use']
        if res.stop_reason != 'tool_use' or not uses:
            return res
        results = []
        for use in uses:
            name, tin, uid = use.get('name'), use.get('input') or {}, use.get('id')
            if stop.is_set():
                results.append({'type': 'tool_result', 'tool_use_id': uid, 'is_error': True,
                                'content': [{'type': 'text', 'text': 'Stopped by the user before this tool ran.'}]})
                res.stopped = True
                continue
            emit('tool_use', {'name': name, 'input': tin, 'id': uid})
            ok = True
            try:
                if handler is None:
                    raise StudioError('no tool handler', 'no_handler')
                out = handler(name, tin, uid)
                blocks = _result_blocks(out)
            except Exception as e:  # noqa: BLE001 - the model gets to see and recover from tool failures
                ok = False
                blocks = [{'type': 'text', 'text': f'Error: {e}'}]
            entry = {'type': 'tool_result', 'tool_use_id': uid, 'content': blocks}
            if not ok:
                entry['is_error'] = True
            results.append(entry)
            summary = text_of(blocks)[:200]
            res.tool_calls.append({'name': name, 'input': tin, 'ok': ok, 'summary': summary})
            emit('tool_result', {'name': name, 'ok': ok, 'summary': summary})
        res.messages.append({'role': 'user', 'content': results})
        if res.stopped:
            break
    else:
        res.hit_max_turns = True
    return res
