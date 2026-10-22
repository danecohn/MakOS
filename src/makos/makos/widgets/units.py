"""Unit conversion for the converter widget (pure)."""
LINEAR = {
    'Length': {'mm': .001, 'cm': .01, 'm': 1, 'km': 1000, 'in': .0254, 'ft': .3048, 'yd': .9144, 'mi': 1609.344},
    'Mass': {'mg': 1e-6, 'g': .001, 'kg': 1, 'oz': .028349523125, 'lb': .45359237, 'st': 6.35029318},
    'Volume': {'ml': .001, 'l': 1, 'tsp': .00492892159375, 'tbsp': .01478676478125, 'cup': .2365882365, 'pt': .473176473, 'gal': 3.785411784},
    'Speed': {'m/s': 1, 'km/h': 1 / 3.6, 'mph': .44704, 'kn': .514444444},
    'Data': {'B': 1, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9, 'TB': 1e12, 'KiB': 1024, 'MiB': 1024 ** 2, 'GiB': 1024 ** 3},
}
TEMPERATURE = ('°C', '°F', 'K')
CATEGORIES = list(LINEAR) + ['Temperature']


def units(category):
    return list(TEMPERATURE) if category == 'Temperature' else list(LINEAR[category])


def convert(value, source, target, category):
    if category == 'Temperature':
        if source not in TEMPERATURE or target not in TEMPERATURE:
            raise ValueError('Unknown unit')
        kelvin = {'°C': value + 273.15, '°F': (value - 32) * 5 / 9 + 273.15, 'K': value}[source]
        if kelvin < 0:
            raise ValueError('Below absolute zero')
        return {'°C': kelvin - 273.15, '°F': (kelvin - 273.15) * 9 / 5 + 32, 'K': kelvin}[target]
    table = LINEAR.get(category)
    if not table or source not in table or target not in table:
        raise ValueError('Unknown unit')
    return value * table[source] / table[target]


def fmt(v):
    return format(v, '.8g')
