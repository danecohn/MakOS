"""Tool-use loop + local bridge client. Pure Python (stdlib urllib); no bpy so it is unit-testable.

`Loop.run` is meant to be called on a WORKER thread; every tool executes through `executor(name, input)` which hands the
call to Blender's main thread and blocks for the result.
"""
import base64
import json
import threading
import time
import urllib.error
import urllib.request

from . import config, prompt, toolspecs

MAX_TURNS = 24
MAX_IMAGES_KEPT = 4
MAX_TOOL_TEXT = 12000


class BridgeError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Cancelled(RuntimeError):
    pass


class Bridge:
    """POST /v1/messages to the local Studio bridge with the per-user token. Never holds an API key."""

    def __init__(self, url=None, token=None, app=config.APP, timeout=300):
        self.url = (url or config.bridge_url()).rstrip('/')
        self.token = token
        self.app = app
        self.timeout = timeout

    def _headers(self):
        token = self.token if self.token is not None else config.read_token()
        h = {'Content-Type': 'application/json', 'X-Amerika-App': self.app, 'Accept': 'application/json'}
        if token:
            h['Authorization'] = 'Bearer ' + token
            h['X-Amerika-Token'] = token
        return h

    def status(self):
        req = urllib.request.Request(self.url + '/v1/status', headers=self._headers())
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def messages(self, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.url + '/v1/messages', data=data, headers=self._headers(), method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get('error', {}).get('message', '')
            except Exception:
                msg = ''
            hint = {401: 'the Studio bridge rejected the token: is amerika-studio-bridge running for this user?',
                    403: 'no Anthropic key for Render: open Studio > Keys.',
                    429: 'rate limited or daily token budget reached.',
                    529: 'the model is overloaded; try again.'}.get(e.code, '')
            raise BridgeError(f'bridge error {e.code}: {msg or hint or e.reason}' + (f' ({hint})' if msg and hint else ''), e.code) from None
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            raise BridgeError('cannot reach the Studio bridge on 127.0.0.1 (start amerika-studio-bridge): ' + str(getattr(e, 'reason', e))) from None


def _text_of(content):
    return ''.join(b.get('text', '') for b in content if b.get('type') == 'text').strip()


def tool_result_blocks(outcome):
    """Convert a tools.call() outcome into (content blocks, is_error)."""
    if outcome.get('ok'):
        body = json.dumps(outcome['result'], separators=(',', ':'))[:MAX_TOOL_TEXT]
        blocks = [{'type': 'text', 'text': body}]
        for png in outcome.get('images') or []:
            blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                                       'data': png if isinstance(png, str) else base64.b64encode(png).decode()}})
        return blocks, False
    return [{'type': 'text', 'text': 'ERROR: ' + str(outcome.get('error', 'failed'))[:MAX_TOOL_TEXT]}], True


def prune_images(messages, keep=MAX_IMAGES_KEPT):
    """Replace all but the newest `keep` images in the history by a text stub (the bridge caps request size)."""
    positions = []
    for mi, m in enumerate(messages):
        if isinstance(m.get('content'), list):
            for bi, b in enumerate(m['content']):
                if b.get('type') == 'tool_result' and isinstance(b.get('content'), list):
                    for ci, c in enumerate(b['content']):
                        if c.get('type') == 'image':
                            positions.append((mi, bi, ci))
    for mi, bi, ci in positions[:-keep] if keep else positions:
        messages[mi]['content'][bi]['content'][ci] = {'type': 'text', 'text': '[older image removed]'}


class Loop:
    def __init__(self, bridge, executor, model=config.DEFAULT_MODEL, system=prompt.SYSTEM, max_turns=MAX_TURNS, max_tokens=4096,
                 on_event=None, cancel=None, tools=None):
        self.bridge, self.executor, self.model, self.system = bridge, executor, model, system
        self.max_turns, self.max_tokens = max_turns, max_tokens
        self.on_event = on_event or (lambda kind, **kw: None)
        self.cancel = cancel or threading.Event()
        self.tools = tools if tools is not None else toolspecs.api_tools()
        self.messages = []
        self.usage = {'input_tokens': 0, 'output_tokens': 0}

    def reset(self):
        self.messages = []

    def run(self, text):
        """Run one user request to completion. Returns {"text", "tool_calls", "turns", "stopped", "error"?}."""
        self.messages.append({'role': 'user', 'content': text})
        calls = []
        final = ''
        for turn in range(1, self.max_turns + 1):
            if self.cancel.is_set():
                return self._result(final, calls, turn - 1, stopped=True)
            self.on_event('thinking', turn=turn)
            prune_images(self.messages)
            body = {'model': self.model, 'max_tokens': self.max_tokens, 'system': self.system, 'messages': self.messages, 'tools': self.tools}
            try:
                resp = self.bridge.messages(body)
            except BridgeError as e:
                self.on_event('error', message=str(e))
                self.messages.pop() if turn == 1 else None
                return self._result(final, calls, turn - 1, error=str(e))
            for k in self.usage:
                self.usage[k] += int((resp.get('usage') or {}).get(k, 0))
            content = resp.get('content') or []
            self.messages.append({'role': 'assistant', 'content': content})
            said = _text_of(content)
            if said:
                final = said
                self.on_event('assistant', text=said)
            uses = [b for b in content if b.get('type') == 'tool_use']
            if not uses:
                stop = resp.get('stop_reason')
                if stop == 'max_tokens':
                    self.on_event('note', text='The reply was cut off (max tokens).')
                return self._result(final, calls, turn)
            results = []
            for u in uses:
                if self.cancel.is_set():
                    results.append({'type': 'tool_result', 'tool_use_id': u['id'], 'is_error': True,
                                    'content': [{'type': 'text', 'text': 'Stopped by the user.'}]})
                    continue
                self.on_event('tool_start', name=u['name'], input=u.get('input'), id=u['id'])
                t0 = time.monotonic()
                try:
                    outcome = self.executor(u['name'], u.get('input') or {})
                except Cancelled:
                    outcome = {'ok': False, 'error': 'Stopped by the user.', 'images': []}
                except Exception as e:  # executor bug must not kill the loop
                    outcome = {'ok': False, 'error': f'internal error: {type(e).__name__}: {e}', 'images': []}
                blocks, is_err = tool_result_blocks(outcome)
                calls.append({'name': u['name'], 'ok': not is_err, 'seconds': round(time.monotonic() - t0, 2),
                              'input': u.get('input'), 'summary': (blocks[0]['text'][:300])})
                self.on_event('tool_end', name=u['name'], ok=not is_err, summary=blocks[0]['text'][:300],
                              images=[b['source']['data'] for b in blocks if b.get('type') == 'image'], id=u['id'])
                r = {'type': 'tool_result', 'tool_use_id': u['id'], 'content': blocks}
                if is_err:
                    r['is_error'] = True
                results.append(r)
            self.messages.append({'role': 'user', 'content': results})
            if self.cancel.is_set():
                return self._result(final, calls, turn, stopped=True)
        self.on_event('note', text=f'Stopped after {self.max_turns} steps.')
        return self._result(final, calls, self.max_turns, truncated=True)

    def _result(self, text, calls, turns, **extra):
        out = {'text': text, 'tool_calls': calls, 'turns': turns, 'usage': dict(self.usage)}
        out.update(extra)
        if extra.get('stopped'):
            # keep the history valid for the next request
            self._close_dangling()
        return out

    def _close_dangling(self):
        if self.messages and self.messages[-1]['role'] == 'assistant':
            uses = [b for b in self.messages[-1]['content'] if b.get('type') == 'tool_use']
            if uses:
                self.messages.append({'role': 'user', 'content': [
                    {'type': 'tool_result', 'tool_use_id': u['id'], 'is_error': True, 'content': [{'type': 'text', 'text': 'Stopped by the user.'}]} for u in uses]})
