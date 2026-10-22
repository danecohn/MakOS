"""Create / prepare Engine projects: install the plugin, apply a template, assemble headlessly."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import recipe as recipe_mod

HERE = Path(__file__).resolve().parent
ADDON_NAME = 'amerika_engine'


def share_dirs():
    env = os.environ.get('AMERIKA_ENGINE_SHARE')
    out = [Path(env)] if env else []
    out += [Path('/usr/share/amerika-engine'), HERE.parent]
    return out


def find_addon():
    for base in share_dirs():
        for rel in ('addons/amerika_engine', 'addons/' + ADDON_NAME):
            p = base / rel
            if (p / 'plugin.cfg').exists():
                return p
    raise FileNotFoundError('amerika_engine addon not found')


def templates_dir():
    for base in share_dirs():
        if (base / 'templates').is_dir():
            return base / 'templates'
    raise FileNotFoundError('no templates directory')


def list_templates():
    out = []
    for d in sorted(templates_dir().iterdir()):
        meta = d / 'template.json'
        if meta.exists():
            out.append(json.loads(meta.read_text()))
    return out


def slug(name):
    s = re.sub(r'[^A-Za-z0-9._ -]+', '', name or '').strip().replace(' ', '-')
    return re.sub(r'-{2,}', '-', s).strip('.-')[:48]


def install_addon(project):
    """Copy the plugin into <project>/addons/amerika_engine (replacing an older copy) and enable it."""
    project = Path(project)
    dest = project / 'addons' / ADDON_NAME
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(find_addon(), dest, ignore=shutil.ignore_patterns('__pycache__', '*.uid', 'templates'))
    enable_plugin(project)
    return dest


def enable_plugin(project):
    pg = Path(project) / 'project.godot'
    line = 'editor_plugins/enabled=PackedStringArray("res://addons/amerika_engine/plugin.cfg")'
    text = pg.read_text() if pg.exists() else 'config_version=5\n'
    if 'amerika_engine/plugin.cfg' in text:
        return
    if '[editor_plugins]' in text:
        text = text.replace('[editor_plugins]\n', '[editor_plugins]\n\n' + line + '\n', 1)
    else:
        text = text.rstrip('\n') + '\n\n[editor_plugins]\n\n' + line + '\n'
    pg.write_text(text)


ICON = (HERE / 'icon.svg') if (HERE / 'icon.svg').exists() else None


def new_project(dest, name, template=None, godot=None, assemble=True):
    """Create a Godot project at `dest` with the plugin; with `template`, copy its recipe and assemble it."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / 'project.godot').exists():
        (dest / 'project.godot').write_text(
            '; Engine configuration file.\nconfig_version=5\n\n[application]\n\n'
            f'config/name={json.dumps(name)}\nconfig/features=PackedStringArray("4.6")\n')
    install_addon(dest)
    for src in share_dirs():
        icon = src / 'icons/amerika-engine-project.svg'
        if icon.exists() and not (dest / 'icon.svg').exists():
            shutil.copy(icon, dest / 'icon.svg')
            break
    if template:
        src = templates_dir() / template / 'amerika_recipe.json'
        if not src.exists():
            raise FileNotFoundError(f'unknown template {template}')
        data = json.loads(src.read_text())
        if name:
            data['name'] = name
        (dest / 'amerika_recipe.json').write_text(json.dumps(data, indent=1) + '\n')
        issues = recipe_mod.errors(recipe_mod.validate(data, dest))
        if issues:
            raise ValueError('template recipe invalid: ' + '; '.join(map(recipe_mod.format_issue, issues)))
        if assemble:
            assemble_project(dest, godot)
    (dest / '.gitignore').write_text('.godot/\n.amerika/\n') if not (dest / '.gitignore').exists() else None
    return dest


def assemble_project(project, godot=None, timeout=120):
    godot = godot or find_godot()
    r = subprocess.run([godot, '--headless', '--path', str(project), '-s', 'res://addons/amerika_engine/cli.gd', '--', 'assemble'],
                       capture_output=True, text=True, timeout=timeout)
    report = None
    for line in r.stdout.splitlines():
        if line.startswith('AMERIKA_REPORT '):
            report = json.loads(line[len('AMERIKA_REPORT '):])
    if report is None or not report.get('ok'):
        raise RuntimeError('assembly failed: ' + (json.dumps(report) if report else r.stdout[-500:] + r.stderr[-500:]))
    subprocess.run([godot, '--headless', '--path', str(project), '--import'], capture_output=True, text=True, timeout=timeout)
    return report


def find_godot():
    env = os.environ.get('AMERIKA_GODOT')
    if env and os.access(env, os.X_OK):
        return env
    for name in ('godot4', 'godot'):
        p = shutil.which(name)
        if p:
            return p
    raise FileNotFoundError('Godot was not found (install the "godot" package or set AMERIKA_GODOT)')
