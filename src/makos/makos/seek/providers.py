"""Seek result providers. Each returns a list of Result; slow ones are meant to run on a worker thread (see engine.query_slow).
Nothing here touches the network: the web shortcut only builds a URL that opens when the user activates it."""
import os
import re
import sqlite3
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .. import catalog
from ..backends import sysutil
from . import index as indexmod
from . import units


@dataclass
class Result:
    group: str          # one of GROUPS
    title: str
    subtitle: str = ''
    icon: str = 'file-generic'
    action: tuple = ()  # ('launch', app_id) | ('pane', id) | ('open', path) | ('copy', text) | ('url', url) | ('none',)
    path: str = ''      # file path for preview / Quick Look
    preview: str = ''   # text shown in the preview pane (definition, contact card, snippet)
    score: float = 0.0
    extra: dict = field(default_factory=dict)


GROUPS = ['Calculator', 'Conversion', 'Applications', 'System Settings', 'Contacts', 'Files', 'Recent', 'Dictionary', 'Web']
WEB_ENGINES = {'duckduckgo': 'https://duckduckgo.com/?q=%s', 'startpage': 'https://www.startpage.com/do/search?q=%s',
               'wikipedia': 'https://en.wikipedia.org/w/index.php?search=%s'}


# ---------------------------------------------------------------- fast providers
def calculator(text):
    if not units.is_expression(text):
        return []
    try:
        value = units.calculate(text)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError):
        return []
    return [Result('Calculator', value, text.strip() + ' =', 'calculator', ('copy', value), score=100)]


def conversion(text):
    out = units.convert(text)
    return [Result('Conversion', out, text.strip(), 'calculator', ('copy', out), score=99)] if out else []


def applications(text, apps=None):
    q = text.casefold().strip()
    if not q:
        return []
    found = []
    for a in (apps if apps is not None else catalog.APPS):
        name = a.name.casefold()
        if q in name or any(w.startswith(q) for w in name.split()):
            found.append(Result('Applications', a.name, 'Application', a.icon, ('launch', a.id), score=90 if name.startswith(q) else 70))
    return sorted(found, key=lambda r: (-r.score, r.title))


def settings_panes(text):
    from ..settings import registry
    if len(text.strip()) < 2:
        return []
    return [Result('System Settings', p.title, 'Settings • ' + p.group, p.icon, ('pane', p.id), score=60) for p in registry.search(text)[:6]]


def web(text, engine='duckduckgo'):
    q = text.strip()
    if len(q) < 2:
        return []
    url = WEB_ENGINES.get(engine, WEB_ENGINES['duckduckgo']) % urllib.parse.quote_plus(q)
    return [Result('Web', f'Search the web for “{q}”', engine.title(), 'browser', ('url', url), score=1)]


# ---------------------------------------------------------------- recent files (GTK recently-used.xbel)
def recent_files(text='', limit=8, xbel=None):
    path = Path(xbel) if xbel else sysutil.data_home() / 'recently-used.xbel'
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    q = text.casefold().strip()
    items = []
    for bm in root.findall('bookmark'):
        href = bm.get('href', '')
        if not href.startswith('file://'):
            continue
        p = urllib.parse.unquote(href[7:])
        if not os.path.isfile(p) or indexmod.is_excluded(p):
            continue
        if q and q not in os.path.basename(p).casefold():
            continue
        items.append((bm.get('modified') or bm.get('visited') or '', p))
    items.sort(reverse=True)
    return [Result('Recent', os.path.basename(p), os.path.dirname(p), 'file-generic', ('open', p), p, score=40) for _t, p in items[:limit]]


# ---------------------------------------------------------------- contacts (read only)
def parse_vcard(text):
    """Contacts from vCard text -> [{'name','emails','phones','org'}]. Line folding and escapes are handled."""
    text = re.sub(r'\r?\n[ \t]', '', text)
    out, cur = [], None
    for line in text.splitlines():
        u = line.upper()
        if u.startswith('BEGIN:VCARD'):
            cur = {'name': '', 'emails': [], 'phones': [], 'org': ''}
        elif u.startswith('END:VCARD') and cur is not None:
            if not cur['name'] and (cur['emails'] or cur['phones']):
                cur['name'] = (cur['emails'] or cur['phones'])[0]
            if cur['name']:
                out.append(cur)
            cur = None
        elif cur is not None and ':' in line:
            key, _, val = line.partition(':')
            field_name = key.split(';')[0].upper()
            val = val.replace('\\,', ',').replace('\\n', ' ').strip()
            if field_name == 'FN':
                cur['name'] = val
            elif field_name == 'N' and not cur['name']:
                parts = [p for p in val.split(';') if p]
                cur['name'] = ' '.join(reversed(parts[:2])) if parts else ''
            elif field_name == 'EMAIL':
                cur['emails'].append(val)
            elif field_name == 'TEL':
                cur['phones'].append(val)
            elif field_name == 'ORG':
                cur['org'] = val.replace(';', ' ').strip()
    return out


def contact_sources(home=None):
    """vCard files/folders and Evolution Data Server address-book databases that exist on this computer."""
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') if home is None else Path(home) / '.local/share'
    home = Path(home or Path.home())
    files = []
    for folder in (data / 'contacts', home / 'Contacts', home / 'Documents/Contacts'):
        try:
            files += sorted(p for p in folder.rglob('*.vcf') if p.is_file())[:500]
        except OSError:
            pass
    dbs = []
    try:
        dbs = sorted((data / 'evolution/addressbook').glob('*/contacts.db'))
    except OSError:
        pass
    return files, dbs


def load_contacts(home=None):
    files, dbs = contact_sources(home)
    people = []
    for f in files:
        try:
            if f.stat().st_size < 5_000_000:
                people += parse_vcard(f.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            continue
    for db in dbs:
        try:
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=2)
            tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
            for t in tables:
                cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
                if 'vcard' in cols:
                    for (vcard,) in con.execute(f'select vcard from "{t}" limit 5000'):
                        if vcard:
                            people += parse_vcard(vcard)
            con.close()
        except sqlite3.Error:
            continue
    return people


def contacts(text, people):
    q = text.casefold().strip()
    if len(q) < 2:
        return []
    out = []
    for p in people:
        hay = ' '.join([p['name'], p['org']] + p['emails'] + p['phones']).casefold()
        if q in hay:
            sub = ' • '.join(x for x in [p['org'], (p['emails'] or [''])[0], (p['phones'] or [''])[0]] if x)
            card = p['name'] + '\n' + '\n'.join(p['emails'] + p['phones'] + ([p['org']] if p['org'] else []))
            out.append(Result('Contacts', p['name'], sub, 'contacts', ('copy', (p['emails'] or p['phones'] or [p['name']])[0]), preview=card, score=50))
    return out[:6]


# ---------------------------------------------------------------- dictionary (offline only)
_DEFINE = re.compile(r'^\s*(?:define|definition of|dict|meaning of)\s+([A-Za-z\'-]{2,40})\s*$', re.I)
WORD = re.compile(r"^[A-Za-z'-]{3,40}$")


def dictionary_backend():
    """('wn'|'dict'|None). WordNet's CLI is preferred; `dict` needs a local dictd server (queried on localhost only)."""
    if sysutil.have('wn'):
        return 'wn'
    if sysutil.have('dict'):
        return 'dict'
    return None


def dictionary(text, backend=None):
    m = _DEFINE.match(text)
    word = m.group(1) if m else (text.strip() if WORD.match(text.strip()) else None)
    backend = backend or dictionary_backend()
    if not word or not backend:
        return []
    if backend == 'wn':
        res = sysutil.run(['wn', word, '-over'], timeout=4)
    else:
        res = sysutil.run(['dict', '-h', 'localhost', word], timeout=4)
    body = res.out.strip() if res.code == 0 else ''
    if not body or 'No information' in body or 'No definitions found' in body:
        return []
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    first = next((ln for ln in lines if re.match(r'^\d+\.', ln)), lines[0])
    return [Result('Dictionary', word, first[:140], 'dictionary', ('copy', first), preview='\n'.join(lines[:14]), score=30)]


# ---------------------------------------------------------------- files: LocalSearch (tracker3) first, our own FTS index second
LOCALSEARCH_SERVICES = ('org.freedesktop.LocalSearch3', 'org.freedesktop.Tracker3.Miner.Files')
SPARQL = ('SELECT DISTINCT ?url WHERE { ?f a nfo:FileDataObject ; nie:url ?url ; fts:match ~q . '
          'FILTER(STRSTARTS(?url, "file://")) } LIMIT 40')


def localsearch_available():
    # MAKOS_SEEK_NO_LOCALSEARCH=1 forces the built-in index (used by the rig to test the fallback deterministically)
    return sysutil.have('tinysparql') and os.environ.get('MAKOS_SEEK_NO_LOCALSEARCH') != '1'


_probe = {'at': 0.0, 'ok': False}


def localsearch_working(max_age=60.0):
    """True when the LocalSearch/Tracker3 endpoint answers a trivial query (cached for a minute). Runs a subprocess: call it
    from a worker thread."""
    import time
    if not localsearch_available():
        return False
    if time.monotonic() - _probe['at'] > max_age:
        _probe['at'] = time.monotonic()
        _probe['ok'] = any(sysutil.run(['tinysparql', 'query', '-b', s, '-q', 'ASK { ?x a nfo:FileDataObject }'], timeout=4).code == 0
                           for s in LOCALSEARCH_SERVICES)
    return _probe['ok']


def localsearch(text, home=None, exclusions=()):
    """Query the LocalSearch/Tracker3 endpoint over D-Bus with a parameterised SPARQL query (the term never becomes query text).
    Returns [] when the service is not running, so the caller falls back to our own index."""
    words = re.findall(r'\w+', text, re.UNICODE)[:6]
    if not words or not localsearch_working():
        return []
    term = ' '.join(w + '*' for w in words)
    for service in LOCALSEARCH_SERVICES:
        res = sysutil.run(['tinysparql', 'query', '-b', service, '-q', SPARQL, '-a', 'q:string:' + term], timeout=6)
        if res.code != 0:
            continue
        paths = []
        for url in re.findall(r'file://\S+', res.out):
            p = urllib.parse.unquote(url.rstrip(',;'))[7:]
            if os.path.isfile(p) and not indexmod.is_excluded(p, home, exclusions):
                paths.append(p)
        return [Result('Files', os.path.basename(p), os.path.dirname(p), 'file-generic', ('open', p), p, score=55) for p in dict.fromkeys(paths)][:12]
    return []


def indexed_files(text, idx):
    return [Result('Files', r['name'], os.path.dirname(r['path']), 'file-generic', ('open', r['path']), r['path'], preview=r['snippet'], score=55)
            for r in idx.search(text, 12)] if idx else []


def files_api(text, roots, limit=12):
    """The Files package's own search (`makos.files.search.search`, also understands kind:/tag:/ext: filters). Called defensively:
    an absent or changed API yields [] so Seek falls through to the next tier."""
    try:
        import importlib
        mod = importlib.import_module('makos.files.search')
        hits = mod.search(text, roots=[str(r) for r in roots], limit=limit)
        out = []
        for h in hits:
            if getattr(h, 'is_dir', False) or indexmod.is_excluded(h.path):
                continue
            out.append(Result('Files', h.name, os.path.dirname(h.path), 'file-generic', ('open', h.path), h.path, preview=getattr(h, 'snippet', ''), score=52))
        return out
    except Exception as error:  # noqa: BLE001
        print('seek: Files search unavailable:', type(error).__name__, flush=True)
        return []


FILTER_WORDS = re.compile(r'(?:^|\s)(?:kind|tag|ext):\S+', re.I)


def walk_fallback(text, home=None, limit=12):
    """Bounded last resort used until the first index exists: file names only, at most 500 directories."""
    home = Path(home or Path.home())
    q = text.casefold().strip()
    if len(q) < 2:
        return []
    found, visited = [], 0
    for root in indexmod.ROOT_NAMES:
        for directory, dirs, files in os.walk(home / root, followlinks=False):
            visited += 1
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink())
            if visited > 500:
                return found
            for name in sorted(files):
                full = Path(directory) / name
                if not name.startswith('.') and q in name.casefold() and not indexmod.is_secret_name(name):
                    found.append(Result('Files', name, directory, 'file-generic', ('open', str(full)), str(full), score=50))
                    if len(found) >= limit:
                        return found
    return found
