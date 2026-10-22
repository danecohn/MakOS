"""Local-only search helpers. No eval, subprocess expressions, or implicit web requests."""
import ast
import math
import operator
import re
from pathlib import Path
from .catalog import APPS

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def calculate(text):
    if len(text) > 120:
        raise ValueError('Expression too long')
    tree = ast.parse(text, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 60:
        raise ValueError('Expression too complex')
    def node(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            v = n.value
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = node(n.operand) * (-1 if isinstance(n.op, ast.USub) else 1)
        elif isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = node(n.left), node(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 10 or abs(a) > 1e8):
                raise ValueError('Power too large')
            v = OPS[type(n.op)](a, b)
        else:
            raise ValueError('Use numbers and arithmetic operators')
        if isinstance(v, complex) or not math.isfinite(v) or abs(v) > 1e30:
            raise ValueError('Result out of range')
        return v
    return format(node(tree.body), '.12g')

UNITS = {'km': ('length', 1000), 'm': ('length', 1), 'cm': ('length', .01),
         'mm': ('length', .001), 'mi': ('length', 1609.344), 'ft': ('length', .3048),
         'in': ('length', .0254), 'kg': ('mass', 1), 'g': ('mass', .001), 'lb': ('mass', .45359237)}


def convert(text):
    match = re.fullmatch(r'\s*(-?[\d.]+)\s*([a-z]+)\s+(?:to|in)\s+([a-z]+)\s*', text.lower())
    if not match:
        return None
    value, a, b = match.groups()
    if a not in UNITS or b not in UNITS or UNITS[a][0] != UNITS[b][0]:
        return None
    return f'{float(value) * UNITS[a][1] / UNITS[b][1]:.10g} {b}'


def applications(query):
    q = query.casefold().strip()
    return [a for a in APPS if q in a.name.casefold()]


def documents(query, home=None, limit=30):
    # Explicitly bounded fallback, never crawl hidden configuration or follow directory symlinks.
    import os
    home = Path(home or Path.home())
    q = query.casefold().strip()
    if len(q) < 2:
        return []
    found, visited = [], 0
    for root in ('Documents', 'Downloads', 'Pictures', 'Desktop'):
        for directory, dirs, files in os.walk(home / root, followlinks=False):
            visited += 1
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink())
            if visited > 500:
                return found
            for name in sorted(files):
                if not name.startswith('.') and q in name.casefold():
                    found.append(Path(directory) / name)
                    if len(found) >= limit:
                        return found
    return found
