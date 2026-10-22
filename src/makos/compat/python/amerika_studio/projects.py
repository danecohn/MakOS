"""The ~/Studio folders, the "New game" starter and recent projects."""
import json
import re
import time
from pathlib import Path

from . import common
from .common import APP_FOLDERS, APPS, StudioError

STARTER_README = """# {name}

Created with Studio on {date}.

* Render/   3D models and scenes (Render). Export .glb files here.
* Engine/   the Godot project (Engine).
* Sprite/   pixel art and animations (Sprite).
* Box/      music (MakBox).

Ask Engine to "import model" to bring Render exports into the game.
"""

GODOT_PROJECT = """; Engine configuration file.
config_version=5

[application]
config/name="{name}"
config/features=PackedStringArray("4.6")
"""


def slug(name):
    s = re.sub(r'[^A-Za-z0-9._ -]+', '', name or '').strip().replace(' ', '-')
    s = re.sub(r'-{2,}', '-', s).strip('.-')
    return s[:48]


def ensure_dirs(paths=None):
    paths = paths or common.Paths()
    for app in APPS:
        paths.project_dir(app).mkdir(parents=True, exist_ok=True)
    return {app: str(paths.project_dir(app)) for app in APPS}


def new_game(name, paths=None):
    """Create <Studio>/{Render,Engine,Sprite,Box}/<slug>/ plus a Godot skeleton. Returns {'name','slug','dirs'}."""
    paths = paths or common.Paths()
    base = slug(name)
    if not base:
        raise StudioError('Give the game a name (letters, digits, spaces, dashes).', 'bad_name')
    ensure_dirs(paths)
    final = base
    n = 2
    while any((paths.project_dir(a) / final).exists() for a in APPS):
        final = f'{base}-{n}'
        n += 1
    dirs = {}
    for app in APPS:
        d = paths.project_dir(app) / final
        d.mkdir(parents=True)
        dirs[app] = str(d)
    eng = Path(dirs['engine'])
    (eng / 'project.godot').write_text(GODOT_PROJECT.format(name=name.strip().replace('"', "'")))
    for sub in ('scenes', 'scripts', 'assets/models', 'assets/sprites', 'assets/audio'):
        (eng / sub).mkdir(parents=True, exist_ok=True)
    (eng / 'README.md').write_text(STARTER_README.format(name=name.strip(), date=time.strftime('%Y-%m-%d')))
    (eng / 'game.json').write_text(json.dumps({'name': name.strip(), 'slug': final, 'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                               'folders': {a: APP_FOLDERS[a] + '/' + final for a in APPS}}, indent=2) + '\n')
    return {'name': name.strip(), 'slug': final, 'dirs': dirs}


def recent_projects(paths=None, limit=8):
    """Newest entries (folders or files) directly inside each ~/Studio/<App> folder: [{app, name, path, mtime}]."""
    paths = paths or common.Paths()
    rows = []
    for app in APPS:
        root = paths.project_dir(app)
        try:
            for p in root.iterdir():
                if p.name.startswith('.'):
                    continue
                rows.append({'app': app, 'name': p.name, 'path': str(p), 'mtime': p.stat().st_mtime})
        except OSError:
            continue
    rows.sort(key=lambda r: r['mtime'], reverse=True)
    return rows[:limit]
