"""Shared assistant state: worker thread, main-thread hand-off, review gating, checkpoints, event log.

No hard bpy import at module level: bpy is only touched from main-thread callbacks, so this is importable in tests.
"""
import json
import queue
import threading
import time

from . import agent, config, prompt, toolspecs

REVIEW_PREVIEW_CHARS = 20000


def describe_call(name, tool_input, ok, summary=''):
    """One human-readable line for the chat panel, e.g. 'create_primitive: Trunk (cylinder)'."""
    i = tool_input if isinstance(tool_input, dict) else {}
    target = i.get('name') or i.get('object') or i.get('collection') or i.get('path') or i.get('armature')
    if not target and isinstance(i.get('objects'), list):
        target = ', '.join(str(x) for x in i['objects'][:3])
    if not target and isinstance(i.get('names'), list):
        target = ', '.join(str(x) for x in i['names'][:3])
    extra = i.get('type') or i.get('mode') or i.get('view') or i.get('material') or i.get('format')
    text = name + (f': {target}' if target else '') + (f' ({extra})' if extra and target else (f': {extra}' if extra else ''))
    if not ok:
        text += ' failed - ' + summary.replace('ERROR: ', '')[:110]
    return text


class MainThread:
    """Run callables on Blender's main thread from other threads."""

    def __init__(self):
        self.q = queue.Queue()
        self.timer_registered = False

    def submit(self, fn, timeout=600, cancel=None):
        box = {}
        ev = threading.Event()
        self.q.put((fn, box, ev))
        deadline = time.monotonic() + timeout
        while not ev.wait(0.1):
            if cancel is not None and cancel.is_set():
                raise agent.Cancelled()
            if time.monotonic() > deadline:
                raise TimeoutError('Blender did not answer in time (is the main thread busy?)')
        if 'exc' in box:
            raise box['exc']
        return box['value']

    def pump(self, budget=0.05):
        """Execute queued callables (main thread). Returns True if something ran."""
        ran = False
        end = time.monotonic() + budget
        while time.monotonic() < end:
            try:
                fn, box, ev = self.q.get_nowait()
            except queue.Empty:
                break
            ran = True
            try:
                box['value'] = fn()
            except BaseException as e:  # noqa: BLE001 - forwarded to the waiting thread
                box['exc'] = e
            ev.set()
        return ran

    def start_timer(self):
        import bpy
        if self.timer_registered:
            return

        def tick():
            self.pump()
            return 0.05

        bpy.app.timers.register(tick, first_interval=0.05, persistent=True)
        self.timer_registered = True

    def pump_until(self, predicate, timeout=300):
        """Background mode (no timer loop): drain the queue until predicate() is true."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump(0.05)
            if predicate():
                return True
            time.sleep(0.01)
        return False


class Session:
    def __init__(self, bridge=None, project_dir=None):
        self.main = MainThread()
        self.bridge = bridge
        self.model = config.DEFAULT_MODEL
        self.review_run_python = True
        self.review_all = False
        self.auto_approve = False      # used by headless/control driven runs
        self.cancel = threading.Event()
        self.busy = False
        self.thread = None
        self.lock = threading.RLock()
        self.events = []               # chat log: dicts with kind/text/time
        self.log = []                  # tool log lines
        self.history = []              # user prompts
        self.pending = None            # review request {id,name,input,code,decision}
        self.last_result = None
        self.loop = None
        self.done = threading.Event()
        self.done.set()
        self.version = 0               # bumps on any change so the UI can redraw
        self.project_dir = project_dir
        self.checkpoint_enabled = True
        self.tools_module = None

    # -- helpers
    def _tools(self):
        if self.tools_module is None:
            from . import tools
            self.tools_module = tools
        return self.tools_module

    def emit(self, kind, **kw):
        with self.lock:
            kw.update(kind=kind, time=time.time())
            self.events.append(kw)
            if len(self.events) > 400:
                del self.events[:100]
            self.version += 1

    def _on_event(self, kind, **kw):
        if kind == 'tool_start':
            self._last_input = kw.get('input')
        if kind == 'tool_end':
            kw = dict(kw, images=len(kw.get('images') or []), label=describe_call(kw['name'], getattr(self, '_last_input', None), kw.get('ok'), kw.get('summary', '')))
        self.emit(kind, **kw)

    # -- execution of tools (worker thread side)
    def needs_review(self, name):
        if name in toolspecs.REVIEW_ALWAYS and self.review_run_python:
            return True
        spec = toolspecs.BY_NAME.get(name)
        return bool(self.review_all and spec and spec['risk'] != 'read')

    def executor(self, name, tool_input):
        """Called on the worker thread by the Loop."""
        if self.needs_review(name) and not self.auto_approve:
            decision = self._ask_review(name, tool_input)
            if decision != 'approve':
                return {'ok': False, 'error': 'The user rejected this action; do not retry it unchanged. Ask what they want instead.', 'images': [], 'code': -32001}
        return self.main.submit(lambda: self._tools().call(name, tool_input), cancel=self.cancel)

    def _ask_review(self, name, tool_input):
        req = {'id': str(time.time()), 'name': name, 'input': tool_input, 'decision': None, 'event': threading.Event(),
               'code': (tool_input or {}).get('code') if isinstance(tool_input, dict) else None}
        with self.lock:
            self.pending = req
            self.version += 1
        self.emit('review', name=name, text=(req['code'] or json.dumps(tool_input))[:REVIEW_PREVIEW_CHARS])
        try:
            while not req['event'].wait(0.1):
                if self.cancel.is_set():
                    req['decision'] = 'reject'
                    break
        finally:
            with self.lock:
                self.pending = None
                self.version += 1
        return req['decision']

    def decide(self, approve):
        with self.lock:
            req = self.pending
        if req:
            req['decision'] = 'approve' if approve else 'reject'
            req['event'].set()
            self.emit('note', text='Approved.' if approve else 'Rejected.')

    # -- requests
    def start(self, text, source='user', workflow=None):
        """Begin a request on a worker thread. Returns False if busy."""
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            self.done.clear()
            self.cancel.clear()
            self.last_result = None
        self.history.append(text)
        self.emit('user', text=text, source=source, workflow=workflow)
        self.thread = threading.Thread(target=self._worker, args=(text, workflow), name='amerika-render-assistant', daemon=True)
        self.thread.start()
        return True

    def _worker(self, text, workflow):
        result = None
        try:
            if self.checkpoint_enabled:
                try:
                    path = self.main.submit(lambda: self._tools().save_checkpoint(self.project_dir, 'request_start'), cancel=self.cancel, timeout=120)
                    self.emit('note', text='Checkpoint saved (undo with the Undo request button).')
                except Exception as e:  # checkpoints are best effort
                    self.emit('note', text=f'No checkpoint: {e}')
            bridge = self.bridge or agent.Bridge()
            if self.loop is None or self.loop.bridge is not bridge:
                self.loop = agent.Loop(bridge, self.executor, model=self.model, on_event=self._on_event, cancel=self.cancel)
            self.loop.model = self.model
            self.loop.executor = self.executor
            result = self.loop.run(text)
            if result.get('error'):
                self.emit('error', text=result['error'])
            elif result.get('stopped'):
                self.emit('note', text='Stopped.')
        except Exception as e:  # keep the app alive
            result = {'text': '', 'error': f'{type(e).__name__}: {e}', 'tool_calls': []}
            self.emit('error', text=result['error'])
        finally:
            with self.lock:
                self.last_result = result
                self.busy = False
                self.version += 1
            self.done.set()

    def stop(self):
        self.cancel.set()
        req = self.pending
        if req:
            req['decision'] = 'reject'
            req['event'].set()

    def wait(self, timeout, pump=False):
        """Wait until the current request finishes. pump=True drives the main-thread queue (background mode)."""
        if pump:
            self.main.pump_until(self.done.is_set, timeout)
        else:
            self.done.wait(timeout)
        return self.done.is_set()

    def new_chat(self):
        if self.loop:
            self.loop.reset()
        self.events.clear()
        self.version += 1

    def undo_request(self):
        def run():
            return self._tools().call('undo', {'checkpoint': 'request_start'})
        out = self.main.submit(run)
        self.emit('note', text='Restored the checkpoint from the start of the last request.' if out.get('ok') else 'Could not restore: ' + str(out.get('error')))
        return out


_session = None


def get_session():
    global _session
    if _session is None:
        _session = Session()
    return _session
