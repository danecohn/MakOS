"""Static and runtime safety for model-written Python (`run_python`). Pure Python, no bpy needed.

This is defence in depth, not a sandbox you may rely on alone: the code is also shown for review
(default ON), has a wall-clock limit and runs with a stripped builtins table and a whitelist import hook.
"""
import ast
import builtins
import io
import sys
import time

ALLOWED_MODULES = {'bpy', 'bmesh', 'mathutils', 'math', 'random', 'colorsys', 'itertools', 'collections', 'bpy_extras'}
# `bpy_extras` is allowed only for object_utils / mesh_utils style helpers; its io/image_utils are blocked below.
BLOCKED_SUBMODULES = {'bpy_extras.io_utils', 'bpy_extras.image_utils', 'bpy_extras.keyconfig_utils', 'bpy_extras.asset_utils'}

BANNED_NAMES = {
    '__import__', 'eval', 'exec', 'compile', 'open', 'input', 'breakpoint', 'globals', 'locals', 'vars', 'dir',
    'getattr', 'setattr', 'delattr', 'memoryview', 'help', 'exit', 'quit', 'copyright', 'credits', 'license',
    'os', 'sys', 'subprocess', 'socket', 'ctypes', 'importlib', 'builtins', 'shutil', 'pathlib', 'io', 'pickle',
    'marshal', 'threading', 'multiprocessing', 'signal', 'urllib', 'http', 'requests', 'asyncio',
    'type', 'super', 'classmethod', 'staticmethod', 'property', 'object',
}
# Attribute names that reach files, processes, the UI scripting layer or other escape hatches.
BANNED_ATTRS = {
    'wm', 'script', 'preferences', 'utils', 'app', 'path', 'msgbus', 'libraries', 'texts', 'text', 'load',
    'save', 'save_render', 'save_as', 'save_as_mainfile', 'save_mainfile', 'open_mainfile', 'quit_blender',
    'python_file_run', 'python_cmd', 'execute_preset', 'handlers', 'timers', 'driver_namespace', 'driver_add',
    'register_class', 'unregister_class', 'system', 'popen', 'spawn', 'fork', 'modules', 'builtins', 'filepath_raw',
    'import_module',
}
BANNED_OPS_PREFIX = ('import_', 'export_')  # bpy.ops.import_scene / export_scene: use the import_file/export_file tools

MAX_SOURCE = 100_000


class UnsafeCode(ValueError):
    def __init__(self, problems):
        self.problems = problems
        super().__init__('; '.join(problems[:8]))


def check(source):
    """Return a list of problem strings (empty list means the code passed the static checks)."""
    problems = []
    if not isinstance(source, str):
        return ['code must be a string']
    if len(source) > MAX_SOURCE:
        return [f'code is longer than {MAX_SOURCE} characters']
    if '\x00' in source:
        return ['code contains a NUL byte']
    try:
        tree = ast.parse(source, mode='exec')
    except SyntaxError as e:
        return [f'syntax error on line {e.lineno}: {e.msg}']
    for node in ast.walk(tree):
        line = getattr(node, 'lineno', 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                problems += _module(alias.name, line)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(f'line {line}: relative imports are not allowed')
            else:
                problems += _module(node.module or '', line)
                for alias in node.names:
                    if alias.name == '*':
                        problems.append(f'line {line}: star imports are not allowed')
                    elif (node.module or '').split('.')[0] == 'bpy' and alias.name in BANNED_ATTRS:
                        problems.append(f'line {line}: importing "{alias.name}" is not allowed')
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES:
                problems.append(f'line {line}: the name "{node.id}" is not allowed')
            elif node.id.startswith('__'):
                problems.append(f'line {line}: dunder name "{node.id}" is not allowed')
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith('_'):
                problems.append(f'line {line}: attribute "{node.attr}" starts with an underscore (not allowed)')
            elif node.attr in BANNED_ATTRS:
                problems.append(f'line {line}: attribute ".{node.attr}" is not allowed (file, process and app-level access is blocked)')
            elif node.attr.startswith(BANNED_OPS_PREFIX):
                problems.append(f'line {line}: ".{node.attr}" is not allowed; use the import_file / export_file tools')
            elif node.attr in BANNED_NAMES and node.attr not in ('type', 'object', 'property', 'dir', 'path', 'io', 'help'):
                problems.append(f'line {line}: attribute ".{node.attr}" is not allowed')
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if '__' in s and s.strip('_') != '':
                problems.append(f'line {line}: string constants containing "__" are not allowed')
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f'line {line}: global/nonlocal statements are not allowed')
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith, ast.Yield, ast.YieldFrom)):
            problems.append(f'line {line}: async/generator constructs are not allowed')
        elif isinstance(node, ast.ClassDef):
            problems.append(f'line {line}: class definitions are not allowed (use functions and data)')
        elif isinstance(node, ast.Lambda):
            pass
    # de-duplicate, keep order
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _module(name, line):
    top = name.split('.')[0]
    if name in BLOCKED_SUBMODULES or any(name.startswith(b + '.') for b in BLOCKED_SUBMODULES):
        return [f'line {line}: import of "{name}" is not allowed']
    if top not in ALLOWED_MODULES:
        return [f'line {line}: import of "{name}" is not allowed (allowed: {", ".join(sorted(ALLOWED_MODULES))})']
    return []


SAFE_BUILTIN_NAMES = (
    'abs all any ascii bin bool bytes callable chr complex dict divmod enumerate filter float format frozenset hash hex '
    'id int isinstance issubclass iter len list map max min next oct ord pow print range repr reversed round set slice '
    'sorted str sum tuple zip True False None Ellipsis NotImplemented '
    'ArithmeticError AssertionError AttributeError Exception IndexError KeyError LookupError NameError '
    'OverflowError RuntimeError StopIteration TypeError ValueError ZeroDivisionError StopAsyncIteration'
).split()


def _import_hook(name, globals=None, locals=None, fromlist=(), level=0):
    top = name.split('.')[0]
    if level or top not in ALLOWED_MODULES or name in BLOCKED_SUBMODULES:
        raise ImportError(f'import of "{name}" is blocked')
    return builtins.__import__(name, globals, locals, fromlist, level)


class Timeout(RuntimeError):
    pass


def run(source, env=None, timeout=20.0):
    """Check then execute `source`. Returns {"stdout": str, "elapsed": float, "result": repr|None}.
    Raises UnsafeCode, Timeout or whatever the code raised."""
    problems = check(source)
    if problems:
        raise UnsafeCode(problems)
    out = io.StringIO()

    def _print(*args, sep=' ', end='\n', **kw):
        out.write(sep.join(str(a) for a in args) + end)
        if out.tell() > 200_000:
            raise RuntimeError('too much output')

    safe = {n: getattr(builtins, n) for n in SAFE_BUILTIN_NAMES if hasattr(builtins, n)}
    safe['print'] = _print
    safe['__import__'] = _import_hook
    glb = {'__builtins__': safe, '__name__': 'amerika_run_python'}
    glb.update(env or {})
    code = compile(source, '<run_python>', 'exec')
    deadline = time.monotonic() + timeout
    counter = [0]

    def tracer(frame, event, arg):
        counter[0] += 1
        if time.monotonic() > deadline:
            raise Timeout(f'run_python exceeded {timeout:g} s')
        return tracer

    old = sys.gettrace()
    start = time.monotonic()
    sys.settrace(tracer)
    try:
        exec(code, glb)
    finally:
        sys.settrace(old)
    return {'stdout': out.getvalue()[-8000:], 'elapsed': round(time.monotonic() - start, 3)}
