"""amerika-engine launcher: opens the Godot editor on a project with the Amerika plugin enabled."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import project, theme

NOTICE = ('Engine is powered by the Godot Engine (MIT licence). Godot is a trademark of the Godot Foundation; '
          'Engine is not affiliated with or endorsed by the Godot Foundation.')


def studio_engine_dir():
    return Path(os.environ.get('AMERIKA_STUDIO_DIR', Path.home() / 'Studio')) / 'Engine'


def config_home():
    return Path(os.environ.get('AMERIKA_ENGINE_CONFIG', Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'amerika-engine'))


def pick_project():
    base = studio_engine_dir()
    cands = [p.parent for p in base.glob('*/project.godot')] if base.exists() else []
    if cands:
        return max(cands, key=lambda p: (p / 'project.godot').stat().st_mtime)
    return None


def build_command(godot, proj):
    return [godot, '--editor', '--path', str(proj)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog='amerika-engine', description='Engine: Godot you talk to. ' + NOTICE)
    ap.add_argument('project', nargs='?', help='project folder (default: the newest in ~/Studio/Engine, or a new first game)')
    ap.add_argument('--new', metavar='NAME', help='create a new project with this name')
    ap.add_argument('--template', help='starter template id (see --list-templates)')
    ap.add_argument('--dir', help='parent folder for --new (default ~/Studio/Engine)')
    ap.add_argument('--list-templates', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='prepare everything but do not start the editor; print the command')
    ap.add_argument('--godot', help='Godot executable')
    ap.add_argument('--version', action='store_true')
    a = ap.parse_args(argv)
    if a.version:
        from . import VERSION
        print('amerika-engine', VERSION, '\n' + NOTICE)
        return 0
    if a.list_templates:
        for t in project.list_templates():
            print(f"{t['id']:18} {t['genre']:16} {t['title']}")
        return 0
    godot = a.godot or project.find_godot()
    cfg = config_home()
    theme.seed(cfg)
    if a.new:
        parent = Path(a.dir) if a.dir else studio_engine_dir()
        proj = project.new_project(parent / project.slug(a.new), a.new, a.template, godot)
    elif a.project:
        proj = Path(a.project).expanduser().resolve()
        if not (proj / 'project.godot').exists():
            print(f'{proj} is not a Godot project (no project.godot). Use --new NAME.', file=sys.stderr)
            return 2
        if not (proj / 'addons/amerika_engine/plugin.cfg').exists():
            project.install_addon(proj)
    else:
        proj = pick_project() or project.new_project(studio_engine_dir() / 'My-First-Game', 'My First Game', a.template or 'platformer_2d', godot)
    # keep the plugin current without touching the user's own files
    if (proj / 'addons/amerika_engine/plugin.cfg').exists():
        project.install_addon(proj)
    if not (proj / 'splash.png').exists():
        try:
            from .splash import make_splash
            make_splash(proj / 'splash.png', proj.name)
        except Exception:
            pass
    env = dict(os.environ, XDG_CONFIG_HOME=str(cfg))
    cmd = build_command(godot, proj)
    if a.dry_run:
        print(' '.join(cmd))
        return 0
    if not os.environ.get('AMERIKA_NO_GAMEMODE') and shutil.which('gamemoderun'):
        cmd = ['gamemoderun'] + cmd  # CPU governor boost while the editor runs (amerika-gamedev)
    os.execvpe(cmd[0], cmd, env)


if __name__ == '__main__':
    sys.exit(main())
