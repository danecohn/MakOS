# Adapted for MakkOS from Amerika OS (src/os/amerika/language.py), GPL-3.0-only, Amerika LLC; MakkOS adaptations.
"""Language & region backend: user-level locale in ~/.config/environment.d (systemd user manager; next login) and system locale via localectl."""
import json
import re
from pathlib import Path

from . import sysutil

LOC_OK = re.compile(r'^[a-z]{2,3}(_[A-Z]{2})?(\.[Uu][Tt][Ff]-?8)?(@[a-z]+)?$')
FORMAT_KEYS = [('LC_TIME', 'Dates and times'), ('LC_NUMERIC', 'Numbers'), ('LC_MONETARY', 'Currency'), ('LC_MEASUREMENT', 'Units'),
               ('LC_COLLATE', 'Sorting'), ('LC_PAPER', 'Paper size')]
ISO = Path('/usr/share/iso-codes/json')


def _names(fname, key_a, key_b, field='name'):
    try:
        data = json.loads((ISO / fname).read_text(encoding='utf-8'))
        top = next(iter(data.values()))
        out = {}
        for e in top:
            for k in (key_a, key_b):
                if k in e:
                    out[e[k]] = e.get(field, '')
        return out
    except (OSError, ValueError, StopIteration):
        return {}


_lang_cache, _country_cache = {}, {}


def describe(locale_name):
    """'de_DE.UTF-8' -> 'German (Germany)'."""
    if not _lang_cache:
        _lang_cache.update(_names('iso_639-3.json', 'alpha_2', 'alpha_3'))
        _country_cache.update(_names('iso_3166-1.json', 'alpha_2', 'alpha_3'))
    base = locale_name.split('.')[0].split('@')[0]
    lang, _, country = base.partition('_')
    lname = (_lang_cache.get(lang) or lang).split(';')[0]
    cname = _country_cache.get(country) or country
    return f'{lname} ({cname})' if country else lname


def installed():
    res = sysutil.run(['locale', '-a'])
    seen, out = set(), []
    for line in res.out.splitlines():
        name = line.strip()
        if name in ('C', 'POSIX') or 'utf' not in name.lower() or '@' in name:
            continue
        canon = name.split('.')[0] + '.UTF-8'
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return sorted(out, key=lambda n: describe(n).lower())


def system_locale():
    res = sysutil.run(['localectl', 'status'])
    m = re.search(r'LANG=(\S+)', res.out)
    return m.group(1) if m else ''


ENV_FILE = 'environment.d/50-makos-locale.conf'


def _env_path():
    return sysutil.config_home() / ENV_FILE


def user_settings():
    """Locale variables MakkOS records for this user (empty when never set)."""
    out = {'language': '', 'lang': '', **{k: '' for k, _t in FORMAT_KEYS}}
    try:
        for line in _env_path().read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                if k == 'LANGUAGE':
                    out['language'] = v
                elif k == 'LANG':
                    out['lang'] = v
                elif k in out:
                    out[k] = v
    except OSError:
        pass
    return out


def _write_env(values):
    """environment.d is read by systemd's user manager at the next login. Only validated locale names are written."""
    allowed = ['LANG', 'LANGUAGE'] + [k for k, _t in FORMAT_KEYS]
    path = _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['# Written by MakkOS Settings (Language & Text). Takes effect at the next login.']
    lines += [f'{k}={values[k]}' for k in allowed if values.get(k)]
    tmp = path.with_suffix('.tmp')
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    tmp.replace(path)


def _current_values():
    cur = user_settings()
    return {'LANG': cur['lang'], 'LANGUAGE': cur['language'], **{k: cur[k] for k, _t in FORMAT_KEYS}}


def check(locale_name):
    if not LOC_OK.match(locale_name or ''):
        raise ValueError('Invalid locale.')
    return locale_name


def set_language(locale_name):
    """Display language for this user (applies at the next login)."""
    check(locale_name)
    vals = _current_values()
    vals['LANG'] = locale_name
    vals['LANGUAGE'] = locale_name.split('.')[0] + ':en_US'
    _write_env(vals)
    return user_settings()


def set_format(key, locale_name):
    if key not in dict(FORMAT_KEYS):
        raise ValueError('Unknown format.')
    check(locale_name)
    vals = _current_values()
    vals[key] = locale_name
    _write_env(vals)
    return user_settings()


def set_all_formats(locale_name):
    check(locale_name)
    vals = _current_values()
    for key, _t in FORMAT_KEYS:
        vals[key] = locale_name
    _write_env(vals)
    return user_settings()


def clear_format(key):
    if key not in dict(FORMAT_KEYS):
        raise ValueError('Unknown format.')
    vals = _current_values()
    vals[key] = ''
    _write_env(vals)
    return user_settings()
