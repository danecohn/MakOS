"""Game Recipe validation: JSON Schema (own small validator, stdlib only) plus the semantic checks the
GDScript assembler also performs (recipe.gd keeps the same error codes).
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
GAMEPLAY = ('platformer_2d', 'topdown_2d', 'third_person_3d', 'first_person_3d')
DIMS = {'platformer_2d': '2d', 'topdown_2d': '2d', 'third_person_3d': '3d', 'first_person_3d': '3d'}


def find_data(name):
    """Locate a shipped data file both in the source tree and in an installed package."""
    for base in (HERE.parent, Path('/usr/share/amerika-engine')):
        for rel in (name, 'addons/amerika_engine/' + name, 'addons/amerika_engine/components/' + name):
            p = base / rel
            if p.exists():
                return p
    raise FileNotFoundError(name)


def load_schema():
    return json.loads(find_data('recipe.schema.json').read_text())


def load_components():
    return json.loads(find_data('components.json').read_text())['components']


# ------------------------------------------------------------------ JSON Schema subset

def _type_ok(value, t):
    if t == 'object':
        return isinstance(value, dict)
    if t == 'array':
        return isinstance(value, list)
    if t == 'string':
        return isinstance(value, str)
    if t == 'boolean':
        return isinstance(value, bool)
    if t == 'integer':
        return isinstance(value, int) and not isinstance(value, bool) or (isinstance(value, float) and value.is_integer())
    if t == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == 'null':
        return value is None
    return False


def validate_schema(value, schema, root=None, path='$'):
    """Return a list of 'path: message' strings."""
    root = root or schema
    errs = []
    if '$ref' in schema:
        ref = schema['$ref']
        node = root
        for part in ref.lstrip('#/').split('/'):
            node = node[part]
        return validate_schema(value, node, root, path)
    if 'const' in schema and value != schema['const']:
        errs.append(f'{path}: must be {schema["const"]!r}')
    if 'enum' in schema and value not in schema['enum']:
        errs.append(f'{path}: must be one of {schema["enum"]}')
    t = schema.get('type')
    if t and not _type_ok(value, t):
        errs.append(f'{path}: expected {t}')
        return errs
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0):
            errs.append(f'{path}: shorter than {schema["minLength"]}')
        if len(value) > schema.get('maxLength', 1 << 30):
            errs.append(f'{path}: longer than {schema["maxLength"]}')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            errs.append(f'{path}: does not match {schema["pattern"]}')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in schema and value < schema['minimum']:
            errs.append(f'{path}: below minimum {schema["minimum"]}')
        if 'maximum' in schema and value > schema['maximum']:
            errs.append(f'{path}: above maximum {schema["maximum"]}')
        if 'exclusiveMinimum' in schema and value <= schema['exclusiveMinimum']:
            errs.append(f'{path}: must be greater than {schema["exclusiveMinimum"]}')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            errs.append(f'{path}: needs at least {schema["minItems"]} items')
        if len(value) > schema.get('maxItems', 1 << 30):
            errs.append(f'{path}: more than {schema["maxItems"]} items')
        if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errs.append(f'{path}: items must be unique')
        if 'items' in schema:
            for i, item in enumerate(value):
                errs += validate_schema(item, schema['items'], root, f'{path}[{i}]')
    if isinstance(value, dict):
        for req in schema.get('required', []):
            if req not in value:
                errs.append(f'{path}: missing "{req}"')
        if len(value) < schema.get('minProperties', 0):
            errs.append(f'{path}: needs at least {schema["minProperties"]} properties')
        props = schema.get('properties', {})
        for key, sub in value.items():
            if 'propertyNames' in schema:
                errs += [e.replace(path, f'{path}.{key} (key)', 1) for e in validate_schema(key, schema['propertyNames'], root, path)]
            if key in props:
                errs += validate_schema(sub, props[key], root, f'{path}.{key}')
            else:
                ap = schema.get('additionalProperties', True)
                if ap is False:
                    errs.append(f'{path}: unknown property "{key}"')
                elif isinstance(ap, dict):
                    errs += validate_schema(sub, ap, root, f'{path}.{key}')
    return errs


# ------------------------------------------------------------------ semantic checks

def _issue(code, path, message, severity='error'):
    return {'code': code, 'path': path, 'message': message, 'severity': severity}


def _param_ok(spec, value):
    t = spec['type']
    if t == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == 'integer':
        return isinstance(value, int) and not isinstance(value, bool) or (isinstance(value, float) and value.is_integer())
    if t == 'boolean':
        return isinstance(value, bool)
    if t in ('string', 'color'):
        return isinstance(value, str)
    if t == 'object':
        return isinstance(value, dict)
    if t == 'string_array':
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return True


def validate(recipe, project_dir=None):
    """Return a list of issue dicts {code,path,message,severity}. Empty = valid and assemblable."""
    issues = []
    for e in validate_schema(recipe, load_schema()):
        path, _, msg = e.partition(': ')
        issues.append(_issue('E_SCHEMA', path, msg))
    if issues:
        return issues
    comps = load_components()
    genre = recipe['genre']
    dims = DIMS.get(genre)
    entities = recipe.get('entities', {})
    audio_music = recipe.get('audio', {}).get('music', {})
    for key, ent in entities.items():
        for i, c in enumerate(ent.get('components', [])):
            base = f'entities.{key}.components[{i}]'
            spec = comps.get(c['type'])
            if spec is None or spec['internal']:
                issues.append(_issue('E_COMPONENT_UNKNOWN', base, f'unknown component "{c["type"]}"'))
                continue
            if dims and dims not in spec['dims']:
                issues.append(_issue('E_COMPONENT_DIMS', base, f'{c["type"]} does not support {dims.upper()} games'))
            for pk, pv in c.items():
                if pk == 'type':
                    continue
                pspec = spec['params'].get(pk)
                if pspec is None:
                    issues.append(_issue('E_PARAM_UNKNOWN', f'{base}.{pk}', f'{c["type"]} has no parameter "{pk}" (has: {", ".join(spec["params"])})'))
                elif not _param_ok(pspec, pv):
                    issues.append(_issue('E_PARAM_TYPE', f'{base}.{pk}', f'expected {pspec["type"]}'))
                elif 'enum' in pspec and pv not in pspec['enum']:
                    issues.append(_issue('E_PARAM_ENUM', f'{base}.{pk}', f'must be one of {pspec["enum"]}'))
                if c['type'] == 'spawner' and pk == 'scene' and isinstance(pv, str) and not pv.startswith('res://') and pv not in entities:
                    issues.append(_issue('E_ENTITY_UNKNOWN', f'{base}.scene', f'spawner scene "{pv}" is not an entity'))
        if ent.get('model') and project_dir is not None:
            rel = ent['model'][len('res://'):]
            if not (Path(project_dir) / rel).exists():
                issues.append(_issue('W_MODEL_MISSING', f'entities.{key}.model', f'{ent["model"]} not found; a placeholder is used', 'warning'))
    if genre in GAMEPLAY:
        if not recipe.get('levels'):
            issues.append(_issue('E_LEVELS_REQUIRED', 'levels', f'{genre} games need at least one level'))
        if not any(e['role'] == 'player' for e in entities.values()):
            issues.append(_issue('E_NO_PLAYER', 'entities', 'no entity with role "player"'))
        for li, level in enumerate(recipe.get('levels', [])):
            base = f'levels[{li}]'
            if 'rows' not in level and 'objects' not in level:
                issues.append(_issue('E_LEVEL_KIND', base, 'a level needs "rows" (grid) or "objects"'))
            legend = level.get('legend', {})
            for ch, ek in legend.items():
                if ek != 'block' and ek not in entities:
                    issues.append(_issue('E_ENTITY_UNKNOWN', f'{base}.legend.{ch}', f'unknown entity "{ek}"'))
            for ri, row in enumerate(level.get('rows', [])):
                for ch in sorted(set(row)):
                    if ch not in legend and ch not in '#. ':
                        issues.append(_issue('E_LEGEND_CHAR', f'{base}.rows[{ri}]', f'character "{ch}" is not in the legend'))
            for oi, obj in enumerate(level.get('objects', [])):
                if obj['entity'] != 'block' and obj['entity'] not in entities:
                    issues.append(_issue('E_ENTITY_UNKNOWN', f'{base}.objects[{oi}]', f'unknown entity "{obj["entity"]}"'))
            if level.get('music') and level['music'] not in audio_music:
                issues.append(_issue('E_AUDIO_KEY', f'{base}.music', f'no audio.music entry "{level["music"]}"'))
        placed = set()
        for level in recipe.get('levels', [])[:1]:
            for ek in level.get('legend', {}).values():
                if any(ch in level.get('legend', {}) and level['legend'][ch] == ek for row in level.get('rows', []) for ch in row):
                    placed.add(ek)
            placed |= {o['entity'] for o in level.get('objects', [])}
        player_keys = [k for k, e in entities.items() if e['role'] == 'player']
        if player_keys and not (set(player_keys) & placed):
            issues.append(_issue('E_PLAYER_NOT_PLACED', 'levels[0]', 'the first level never places the player entity'))
    if genre == 'visual_novel':
        story = recipe.get('story')
        if not story:
            issues.append(_issue('E_STORY_REQUIRED', 'story', 'visual_novel games need a story'))
        else:
            nodes = story['nodes']
            if story['start'] not in nodes:
                issues.append(_issue('E_STORY_NODE', 'story.start', f'unknown node "{story["start"]}"'))
            for nid, n in nodes.items():
                if 'next' in n and n['next'] not in nodes:
                    issues.append(_issue('E_STORY_NODE', f'story.nodes.{nid}.next', f'unknown node "{n["next"]}"'))
                for ci, ch in enumerate(n.get('choices', [])):
                    if ch['goto'] not in nodes:
                        issues.append(_issue('E_STORY_NODE', f'story.nodes.{nid}.choices[{ci}]', f'unknown node "{ch["goto"]}"'))
    return issues


def errors(issues):
    return [i for i in issues if i['severity'] == 'error']


def format_issue(i):
    return f'{i["code"]} {i["path"]}: {i["message"]}'
