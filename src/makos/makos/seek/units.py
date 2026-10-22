"""Calculator and unit conversion for Seek. Pure functions, no eval: a bounded AST walk with a fixed operator allowlist,
and a unit table (length, mass, volume, temperature, speed, data, time, area). No currency (it would need the network)."""
import ast
import math
import operator
import re

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def calculate(text):
    """Evaluate arithmetic. Raises ValueError/SyntaxError/ZeroDivisionError/OverflowError for anything else."""
    if len(text) > 120:
        raise ValueError('Expression too long')
    text = text.replace('×', '*').replace('÷', '/').replace('^', '**').replace(',', '.')
    tree = ast.parse(text.strip(), mode='eval')
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


def is_expression(text):
    """True when the text looks like arithmetic worth evaluating (has an operator and a digit)."""
    return bool(re.search(r'\d', text)) and bool(re.search(r'[-+*/%^×÷]', text.lstrip('+-')))


# ---------------------------------------------------------------- units
# dimension -> {unit name: factor to the base unit}; temperature is handled separately.
TABLE = {
    'length': {'m': 1, 'km': 1000, 'cm': .01, 'mm': .001, 'um': 1e-6, 'nm': 1e-9, 'mi': 1609.344, 'yd': .9144, 'ft': .3048, 'in': .0254, 'nmi': 1852},
    'mass': {'kg': 1, 'g': .001, 'mg': 1e-6, 't': 1000, 'lb': .45359237, 'oz': .028349523125, 'st': 6.35029318},
    'volume': {'l': 1, 'ml': .001, 'cl': .01, 'm3': 1000, 'gal': 3.785411784, 'qt': .946352946, 'pt': .473176473, 'cup': .2365882365,
               'floz': .0295735295625, 'tbsp': .01478676478125, 'tsp': .00492892159375},
    'speed': {'m/s': 1, 'km/h': 1 / 3.6, 'mph': .44704, 'kn': .514444444, 'ft/s': .3048},
    'data': {'b': 1 / 8, 'B': 1, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9, 'TB': 1e12, 'KiB': 1024, 'MiB': 1024 ** 2, 'GiB': 1024 ** 3, 'TiB': 1024 ** 4},
    'time': {'s': 1, 'ms': .001, 'min': 60, 'h': 3600, 'd': 86400, 'wk': 604800},
    'area': {'m2': 1, 'km2': 1e6, 'cm2': 1e-4, 'ha': 1e4, 'acre': 4046.8564224, 'ft2': .09290304, 'mi2': 2589988.110336},
}
# spelling -> canonical unit (lower-case lookups, except data units which are case sensitive)
ALIASES = {
    'meter': 'm', 'meters': 'm', 'metre': 'm', 'metres': 'm', 'kilometer': 'km', 'kilometers': 'km', 'kilometre': 'km', 'kilometres': 'km',
    'centimeter': 'cm', 'centimeters': 'cm', 'millimeter': 'mm', 'millimeters': 'mm', 'mile': 'mi', 'miles': 'mi', 'yard': 'yd', 'yards': 'yd',
    'foot': 'ft', 'feet': 'ft', 'inch': 'in', 'inches': 'in', 'kilogram': 'kg', 'kilograms': 'kg', 'kilo': 'kg', 'kilos': 'kg', 'gram': 'g', 'grams': 'g',
    'pound': 'lb', 'pounds': 'lb', 'lbs': 'lb', 'ounce': 'oz', 'ounces': 'oz', 'stone': 'st', 'tonne': 't', 'tonnes': 't',
    'liter': 'l', 'liters': 'l', 'litre': 'l', 'litres': 'l', 'milliliter': 'ml', 'milliliters': 'ml', 'gallon': 'gal', 'gallons': 'gal',
    'quart': 'qt', 'quarts': 'qt', 'pint': 'pt', 'pints': 'pt', 'cups': 'cup', 'tablespoon': 'tbsp', 'teaspoon': 'tsp', 'fl oz': 'floz',
    'kph': 'km/h', 'kmh': 'km/h', 'kmph': 'km/h', 'knot': 'kn', 'knots': 'kn', 'mps': 'm/s',
    'second': 's', 'seconds': 's', 'sec': 's', 'minute': 'min', 'minutes': 'min', 'hour': 'h', 'hours': 'h', 'hr': 'h', 'day': 'd', 'days': 'd',
    'week': 'wk', 'weeks': 'wk', 'sqm': 'm2', 'hectare': 'ha', 'hectares': 'ha', 'acres': 'acre', 'sqft': 'ft2',
    'byte': 'B', 'bytes': 'B', 'bit': 'b', 'bits': 'b',
}
TEMP = {'c': 'C', 'celsius': 'C', '°c': 'C', 'degc': 'C', 'f': 'F', 'fahrenheit': 'F', '°f': 'F', 'degf': 'F', 'k': 'K', 'kelvin': 'K', '°k': 'K'}
_DATA_CI = {k.lower(): k for k in TABLE['data'] if k not in ('b', 'B')}
_UNIT_INDEX = {}
for _dim, _units in TABLE.items():
    for _u in _units:
        if _dim != 'data':
            _UNIT_INDEX[_u.lower()] = (_dim, _u)
for _a, _u in ALIASES.items():
    for _dim, _units in TABLE.items():
        if _u in _units:
            _UNIT_INDEX[_a] = (_dim, _u)

_PATTERN = re.compile(r'^\s*(-?\d+(?:[.,]\d+)?(?:e[+-]?\d+)?)\s*([^\d\s][^\s]*(?:\s+oz)?)\s+(?:to|in|into|as)\s+([^\d\s][^\s]*(?:\s+oz)?)\s*$', re.I)


def _lookup(word):
    """(dimension, canonical unit) for a spelling, or None. Data units keep their case (kB/KB/MB are decimal, KiB binary)."""
    raw = word.strip()
    low = raw.lower().rstrip('.')
    if raw in TABLE['data']:
        return 'data', raw
    if low in _DATA_CI:
        return 'data', _DATA_CI[low]
    if low in ('kb', 'kilobyte', 'kilobytes'):
        return 'data', 'KB'
    if low in ('megabyte', 'megabytes'):
        return 'data', 'MB'
    if low in ('gigabyte', 'gigabytes'):
        return 'data', 'GB'
    if low in ('terabyte', 'terabytes'):
        return 'data', 'TB'
    if low in TEMP:
        return 'temperature', TEMP[low]
    return _UNIT_INDEX.get(low) or _data_alias(low)


def _data_alias(low):
    unit = ALIASES.get(low)
    return ('data', unit) if unit in TABLE['data'] else None


def _temperature(value, a, b):
    kelvin = {'C': value + 273.15, 'F': (value - 32) * 5 / 9 + 273.15, 'K': value}[a]
    if kelvin < 0:
        raise ValueError('Below absolute zero')
    return {'C': kelvin - 273.15, 'F': (kelvin - 273.15) * 9 / 5 + 32, 'K': kelvin}[b]


def convert(text):
    """'5 ft to cm' -> '152.4 cm'. Returns None when the text is not a conversion of two compatible units."""
    m = _PATTERN.match(text)
    if not m:
        return None
    num, a_word, b_word = m.groups()
    try:
        value = float(num.replace(',', '.'))
    except ValueError:
        return None
    a, b = _lookup(a_word), _lookup(b_word)
    if not a or not b or a[0] != b[0]:
        return None
    if a[0] == 'temperature':
        try:
            out = _temperature(value, a[1], b[1])
        except ValueError:
            return None
    else:
        table = TABLE[a[0]]
        out = value * table[a[1]] / table[b[1]]
    if not math.isfinite(out):
        return None
    return f'{out:.10g} {b_word.strip()}'
