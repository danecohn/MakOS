#!/usr/bin/env python3
"""Compile original cursor sources with a provided system xcursorgen binary."""
import argparse
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--xcursorgen',default='xcursorgen')
    a=ap.parse_args()
    source=ROOT/'src/makos/cursors'
    target=ROOT/'src/makos/icons/MakOS-Cursors'
    (target/'cursors').mkdir(parents=True,exist_ok=True)
    for config in source.glob('*.cursor'):
        subprocess.run([a.xcursorgen,str(config),str(target/'cursors'/config.stem)],cwd=source,check=True)
    aliases={'left_ptr':'arrow','default':'arrow','text':'ibeam','xterm':'ibeam','pointer':'pointer-hand','hand2':'pointer-hand','cross':'crosshair','wait':'busy-spinner','watch':'busy-spinner','progress':'busy-spinner','ew-resize':'resize-horizontal','size_hor':'resize-horizontal','ns-resize':'resize-vertical','size_ver':'resize-vertical','nwse-resize':'resize-diagonal-1','nesw-resize':'resize-diagonal-2'}
    for alias,name in aliases.items():
        link=target/'cursors'/alias
        link.unlink(missing_ok=True);link.symlink_to(name)
    (target/'index.theme').write_text('[Icon Theme]\nName=MakOS Cursors\nComment=Original silver and blue pointers\n')
    print('Compiled cursor theme:',target)
if __name__=='__main__':main()
