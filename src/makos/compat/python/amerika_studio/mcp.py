"""amerika-studio-mcp: a stdio MCP server exposing render_*, engine_*, sprite_*, box_* tools.

The tool list comes from the shared tools.json. Each call is forwarded as JSON-RPC to the app's control endpoint
($XDG_RUNTIME_DIR/amerika/studio-<app>.json). Apps are launched through their launcher when needed. Tools of risk class
`critical` (code execution) always need a fresh approval from the user, asked through `amerika-studio-approve`.
"""
import json
import os
import subprocess
import sys
import threading

from . import __version__, common, control
from .common import APPS, StudioError

INSTRUCTIONS = (
    'These tools drive Studio, the user\'s game-making apps: Render (3D, Blender), Engine (Godot), '
    'Sprite (pixel art) and MakBox (chiptune music). Tool names are <app>_<area>_<action>. Start with a read '
    'tool (scene_info, project_info, canvas_info, song_get), make small changes, then verify (screenshot, describe). '
    '<app>_app_prompt hands a plain-language instruction to the app\'s own Claude assistant. Files are confined to the '
    'project folder (~/Studio/<App>). Tools that run code ask the user for approval every time; if declined, do not retry.')

EXTRA_TOOLS = [
    {'name': 'studio_status', 'description': 'List the four Studio apps: installed, running, ready.',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'annotations': {'readOnlyHint': True}},
    {'name': 'studio_launch', 'description': 'Start a Studio app (if not running) and wait until it is ready.',
     'inputSchema': {'type': 'object', 'properties': {'app': {'type': 'string', 'enum': list(APPS)}}, 'required': ['app'],
                     'additionalProperties': False}, 'annotations': {'readOnlyHint': False}},
]


def mcp_name(app, tool):
    return f'{app}_{tool.replace(".", "_")}'


def build_registry(doc=None):
    """{mcp_name: {'app','tool','method','spec','risk','timeout'}} from tools.json."""
    doc = doc or common.load_tools()
    reg = {}
    for app, info in doc['apps'].items():
        for t in info['tools']:
            reg[mcp_name(app, t['name'])] = {'app': app, 'tool': t['name'], 'method': f'{app}.{t["name"]}', 'spec': t,
                                             'risk': t.get('risk', 'act'), 'timeout': int(t.get('timeout', 60))}
    return reg


def list_tools(reg):
    out = []
    for name, e in reg.items():
        title = common.APP_TITLES[e['app']]
        out.append({'name': name, 'description': f'[{title}] {e["spec"]["description"]} (risk: {e["risk"]})',
                    'inputSchema': e['spec']['inputSchema'],
                    'annotations': {'readOnlyHint': e['risk'] == 'read', 'destructiveHint': e['risk'] == 'critical',
                                    'idempotentHint': False, 'openWorldHint': False}})
    return out + EXTRA_TOOLS


# ------------------------------------------------------------------------------------------------ validation
_TYPES = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'object': dict, 'array': list}


def validate(value, schema, path='arguments'):
    """Small JSON-Schema subset validator (type, properties, required, additionalProperties, enum, min/max, maxLength,
    items, maxItems). Returns a list of error strings."""
    errs = []
    t = schema.get('type')
    if t:
        py = _TYPES[t]
        if not isinstance(value, py) or (t in ('integer', 'number') and isinstance(value, bool)):
            return [f'{path}: expected {t}']
    if 'enum' in schema and value not in schema['enum']:
        errs.append(f'{path}: must be one of {schema["enum"]}')
    if isinstance(value, str) and len(value) > schema.get('maxLength', 10 ** 9):
        errs.append(f'{path}: longer than {schema["maxLength"]}')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in schema and value < schema['minimum']:
            errs.append(f'{path}: below minimum {schema["minimum"]}')
        if 'maximum' in schema and value > schema['maximum']:
            errs.append(f'{path}: above maximum {schema["maximum"]}')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for r in schema.get('required', []):
            if r not in value:
                errs.append(f'{path}: missing required "{r}"')
        for k, v in value.items():
            if k in props:
                errs += validate(v, props[k], f'{path}.{k}')
            elif schema.get('additionalProperties') is False:
                errs.append(f'{path}: unknown field "{k}"')
    if isinstance(value, list):
        if len(value) > schema.get('maxItems', 10 ** 9):
            errs.append(f'{path}: more than {schema["maxItems"]} items')
        if 'items' in schema:
            for i, v in enumerate(value):
                errs += validate(v, schema['items'], f'{path}[{i}]')
    return errs


# ------------------------------------------------------------------------------------------------ approval
def approve(entry, args):
    """Ask the user to approve a critical tool call. True only on an explicit yes."""
    cmd = os.environ.get('AMERIKA_STUDIO_APPROVER', 'amerika-studio-approve')
    summary = args.get('description') or ''
    detail = args.get('code') or json.dumps(args, ensure_ascii=False)
    try:
        r = subprocess.run([cmd, '--app', entry['app'], '--tool', entry['tool'], '--summary', str(summary)[:300]],
                           input=str(detail)[:20000], text=True, capture_output=True, timeout=150)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


# ------------------------------------------------------------------------------------------------ server
class Server:
    def __init__(self, reg=None, paths=None, approver=approve, launcher=None, rpc=control.rpc):
        self.reg = reg or build_registry()
        self.paths = paths or common.Paths()
        self.approver = approver
        self.launcher = launcher or (lambda app: control.launch(app, paths=self.paths))
        self.rpc = rpc
        self.autolaunch = os.environ.get('AMERIKA_STUDIO_MCP_AUTOLAUNCH', '1') != '0'

    def status(self):
        out = {}
        for app in APPS:
            p = control.ping(app, self.paths)
            out[app] = {'installed': control.installed(app), 'running': bool(p), 'ready': bool(p and p.get('ready', True))}
        return out

    def descriptor_for(self, app):
        d = control.read_descriptor(app, self.paths)
        if d and (control.ping(app, self.paths) or {}).get('ready', False):
            return d
        if not self.autolaunch:
            raise StudioError(f'{common.APP_TITLES[app]} is not running. Call studio_launch first.', 'not_running')
        return self.launcher(app)

    def call_tool(self, name, args):
        """Returns MCP content list; raises StudioError / RpcError for failures (turned into isError by the caller)."""
        if name == 'studio_status':
            return [{'type': 'text', 'text': json.dumps(self.status())}]
        if name == 'studio_launch':
            errs = validate(args, EXTRA_TOOLS[1]['inputSchema'])
            if errs:
                raise StudioError('; '.join(errs), 'invalid_params')
            d = self.launcher(args['app'])
            return [{'type': 'text', 'text': json.dumps({'app': args['app'], 'ready': bool(d)})}]
        entry = self.reg.get(name)
        if entry is None:
            raise StudioError(f'unknown tool {name}', 'unknown_tool')
        errs = validate(args, entry['spec']['inputSchema'])
        if errs:
            raise StudioError('invalid arguments: ' + '; '.join(errs[:5]), 'invalid_params')
        if entry['risk'] == 'critical' and not self.approver(entry, args):
            raise StudioError('The user declined (or could not be asked to approve) this action. Do not retry unless asked.', 'declined')
        desc = self.descriptor_for(entry['app'])
        result = self.rpc(desc, entry['method'], args, timeout=entry['timeout'])
        return result_to_content(result)


def result_to_content(result):
    """JSON result -> MCP content: images become image blocks, the rest one JSON text block."""
    content = []
    rest = result
    if isinstance(result, dict) and isinstance(result.get('images'), list):
        rest = {k: v for k, v in result.items() if k != 'images'}
        for img in result['images']:
            if isinstance(img, dict) and img.get('base64'):
                content.append({'type': 'image', 'data': img['base64'], 'mimeType': img.get('mime', 'image/png')})
    if rest not in (None, {}) or not content:
        content.insert(0, {'type': 'text', 'text': json.dumps(rest if rest is not None else {'ok': True}, ensure_ascii=False)})
    return content


def serve(server, stdin=sys.stdin, stdout=sys.stdout):
    lock = threading.Lock()
    threads = []

    def send(obj):
        with lock:
            stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
            stdout.flush()

    def run_call(mid, params):
        name, args = params.get('name', ''), params.get('arguments') or {}
        try:
            content = server.call_tool(name, args)
            send({'jsonrpc': '2.0', 'id': mid, 'result': {'content': content}})
        except (StudioError, control.RpcError) as e:
            send({'jsonrpc': '2.0', 'id': mid, 'result': {'isError': True, 'content': [{'type': 'text', 'text': str(e)}]}})
        except Exception as e:  # noqa: BLE001 - one bad call must not kill the server
            send({'jsonrpc': '2.0', 'id': mid, 'result': {'isError': True, 'content': [{'type': 'text', 'text': f'internal error: {type(e).__name__}'}]}})

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'parse error'}})
            continue
        if not isinstance(msg, dict):
            continue
        mid, method, params = msg.get('id'), msg.get('method'), msg.get('params') or {}
        if method is None or mid is None:
            continue
        if method == 'initialize':
            send({'jsonrpc': '2.0', 'id': mid, 'result': {
                'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': 'amerika-studio', 'version': __version__}, 'instructions': INSTRUCTIONS}})
        elif method == 'ping':
            send({'jsonrpc': '2.0', 'id': mid, 'result': {}})
        elif method == 'tools/list':
            send({'jsonrpc': '2.0', 'id': mid, 'result': {'tools': list_tools(server.reg)}})
        elif method == 'tools/call':
            t = threading.Thread(target=run_call, args=(mid, params), daemon=True)
            t.start()
            threads.append(t)
        else:
            send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'method not found: {method}'}})
    for t in threads:       # stdin closed: let running calls finish their answers
        t.join(timeout=5)


def restore_env(environ=os.environ):
    """OpenClaw starts stdio servers with a minimal environment. Restore what the control endpoints (XDG_RUNTIME_DIR) and the
    approval dialog (Wayland, session bus) need, for the current user only."""
    runtime = environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    environ['XDG_RUNTIME_DIR'] = runtime
    if not environ.get('WAYLAND_DISPLAY'):
        try:
            socks = sorted(n for n in os.listdir(runtime) if n.startswith('wayland-') and not n.endswith('.lock'))
        except OSError:
            socks = []
        if socks:
            environ['WAYLAND_DISPLAY'] = socks[0]
    if not environ.get('DBUS_SESSION_BUS_ADDRESS') and os.path.exists(os.path.join(runtime, 'bus')):
        environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path={runtime}/bus'


def main(argv=None):
    restore_env()
    serve(Server())
    return 0


if __name__ == '__main__':
    sys.exit(main())
