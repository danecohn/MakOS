"""Tiny JSON-schema validator (the subset the tool schemas use). Pure Python, no bpy."""
import math

TYPES = {
    'object': dict, 'array': (list, tuple), 'string': str, 'boolean': bool,
}


class ValidationError(ValueError):
    pass


def _type_ok(value, name):
    if name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if name == 'null':
        return value is None
    return isinstance(value, TYPES[name]) and not (name != 'boolean' and isinstance(value, bool) and name in ('object', 'array', 'string'))


def validate(value, schema, path='input'):
    """Return a cleaned copy of `value` (defaults filled, ints coerced to float where asked) or raise."""
    types = schema.get('type')
    if types is not None:
        names = types if isinstance(types, list) else [types]
        # allow integral floats for integer, ints for number
        if 'integer' in names and isinstance(value, float) and value.is_integer() and 'number' not in names:
            value = int(value)
        if not any(_type_ok(value, n) for n in names):
            raise ValidationError(f'{path}: expected {"/".join(names)}, got {type(value).__name__}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValidationError(f'{path}: {value!r} is not one of {schema["enum"]}')
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if 'minimum' in schema and value < schema['minimum']:
            raise ValidationError(f'{path}: {value} is below the minimum {schema["minimum"]}')
        if 'maximum' in schema and value > schema['maximum']:
            raise ValidationError(f'{path}: {value} is above the maximum {schema["maximum"]}')
        return value
    if isinstance(value, str):
        if 'maxLength' in schema and len(value) > schema['maxLength']:
            raise ValidationError(f'{path}: longer than {schema["maxLength"]} characters')
        if 'minLength' in schema and len(value) < schema['minLength']:
            raise ValidationError(f'{path}: shorter than {schema["minLength"]} characters')
        return value
    if isinstance(value, (list, tuple)):
        if 'minItems' in schema and len(value) < schema['minItems']:
            raise ValidationError(f'{path}: needs at least {schema["minItems"]} items')
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            raise ValidationError(f'{path}: allows at most {schema["maxItems"]} items')
        item = schema.get('items')
        if item is None:
            return list(value)
        return [validate(v, item, f'{path}[{i}]') for i, v in enumerate(value)]
    if isinstance(value, dict):
        props = schema.get('properties')
        if props is None:
            return dict(value)
        out = {}
        for key in schema.get('required', []):
            if key not in value:
                raise ValidationError(f'{path}: missing required field "{key}"')
        extra = [k for k in value if k not in props]
        if extra and schema.get('additionalProperties', True) is False:
            raise ValidationError(f'{path}: unknown field(s) {sorted(extra)}; allowed: {sorted(props)}')
        for key, sub in props.items():
            if key in value:
                out[key] = validate(value[key], sub, f'{path}.{key}')
            elif 'default' in sub:
                out[key] = sub['default']
        for key in extra:
            out[key] = value[key]
        return out
    return value
