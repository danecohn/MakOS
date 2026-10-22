#!/usr/bin/env python3
"""Regenerate src/makos/applications/*.desktop from makos.catalog so names, icons and Exec stay consistent."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/makos'))
from makos import catalog  # noqa: E402

OUT = ROOT / 'src/makos/applications'


def entry(app):
    lines = ['[Desktop Entry]', 'Type=Application', f'Name={app.name}', f'Exec=makos-app {app.id} %U', f'Icon=makos-{app.icon}', 'Terminal=false',
             'OnlyShowIn=MakkOS;MakOS;', f'Categories={app.categories}', 'StartupNotify=true', f"StartupWMClass={'Euro-Office' if app.id in ('paper', 'digits', 'slides') else 'org.makos.Apps.' + app.id.replace('-', '_') if app.internal and app.id not in ('seek', 'spread', 'desktops', 'widgets', 'trash-empty') else 'MakkSocial' if app.id == 'social' else 'makos-' + app.id}"]
    if app.mime:
        lines.append(f'MimeType={app.mime}')
    if app.keywords:
        lines.append(f'Keywords={app.keywords}')
    return '\n'.join(lines) + '\n'


def main():
    OUT.mkdir(exist_ok=True)
    for app in catalog.APPS:
        (OUT / f'makos-{app.id}.desktop').write_text(entry(app))
    print('desktop entries:', len(catalog.APPS))


if __name__ == '__main__':
    main()
