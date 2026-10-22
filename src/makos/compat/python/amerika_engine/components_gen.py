"""Derive components.json from the @export lines and header tags of the GDScript components.

The scripts are the source of truth. `components.json` (committed, shipped next to them) lets the GDScript
assembler and the Python validator agree on component names, parameters, types and defaults without parsing GDScript
at runtime. tests/test_studio_engine.py regenerates it and fails when the committed copy has drifted.
"""
import json
import re
import sys
from pathlib import Path

HEADER = re.compile(r'^## @(\w+)\s*(.*)$')
EXPORT = re.compile(r'^@export(?:_enum\((?P<enum>[^)]*)\))?\s+var\s+(?P<name>\w+)\s*:\s*(?P<type>[\w\[\]]+)\s*=\s*(?P<default>.+?)(?:\s+##\s*(?P<doc>.*))?$')

TYPES = {'float': 'number', 'int': 'integer', 'bool': 'boolean', 'String': 'string', 'Color': 'color',
         'Dictionary': 'object', 'Array[String]': 'string_array'}


def parse_default(kind, text):
    text = text.strip()
    if kind == 'number' or kind == 'integer':
        return float(text) if kind == 'number' else int(text)
    if kind == 'boolean':
        return text == 'true'
    if kind == 'string':
        return json.loads(text)
    if kind == 'color':
        m = re.match(r'Color\(([^)]*)\)', text)
        parts = [float(x) for x in m.group(1).split(',')]
        return '#' + ''.join('%02x' % round(max(0.0, min(1.0, v)) * 255) for v in parts[:3])
    if kind == 'object':
        return {}
    if kind == 'string_array':
        return []
    raise ValueError(f'unsupported default for {kind}: {text}')


def parse_component(path):
    info = {'script': 'res://addons/amerika_engine/components/' + path.name, 'dims': ['2d', '3d'], 'mover': False,
            'internal': False, 'summary': '', 'params': {}}
    for line in path.read_text().splitlines():
        m = HEADER.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == 'component':
                info['name'] = val
            elif key == 'dims':
                info['dims'] = [d.strip() for d in val.split(',')]
            elif key == 'mover':
                info['mover'] = val == 'true'
            elif key == 'internal':
                info['internal'] = val == 'true'
            elif key == 'summary':
                info['summary'] = val
            continue
        m = EXPORT.match(line)
        if m:
            kind = TYPES[m.group('type')]
            spec = {'type': kind, 'default': parse_default(kind, m.group('default')), 'doc': (m.group('doc') or '').strip()}
            if m.group('enum'):
                spec['enum'] = [json.loads(x.strip()) for x in m.group('enum').split(',')]
            info['params'][m.group('name')] = spec
    if 'name' not in info:
        raise ValueError(f'{path}: missing "## @component" header')
    return info


def generate(components_dir):
    comps = {}
    for path in sorted(Path(components_dir).glob('*.gd')):
        if path.name == 'component.gd':
            continue
        info = parse_component(path)
        comps[info.pop('name')] = info
    return {'version': 1, 'components': comps}


def render(data):
    return json.dumps(data, indent=1, sort_keys=False) + '\n'


if __name__ == '__main__':
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'addons/amerika_engine'
    out = base / 'components/components.json'
    out.write_text(render(generate(base / 'components')))
    print('wrote', out)
