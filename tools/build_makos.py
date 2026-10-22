#!/usr/bin/env python3
"""Build only MakOS, in a separate local testing channel; never publish."""
import argparse
import importlib.util
import sys
import subprocess
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-repo',action='store_true')
    parser.add_argument('--only',help='comma-separated MakOS package names; existing package files are retained')
    args=parser.parse_args()
    for script in ('make_makos_vectors.py','make_makos_materials.py'):
        subprocess.run([sys.executable,str(ROOT/'tools'/script)],check=True)
    subprocess.run([sys.executable,str(ROOT/'tools/ingest_makos_assets.py'),'--normalize','--require-all'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable,str(ROOT/'tools/prepare_makos_wallpapers.py')],check=True)
    (ROOT/'src/makos/wallpapers').mkdir(parents=True,exist_ok=True)
    import shutil
    cursor=os.environ.get('MAKOS_XCURSORGEN') or shutil.which('xcursorgen')
    if cursor:
        subprocess.run([sys.executable,str(ROOT/'tools/build_makos_cursors.py'),'--xcursorgen',cursor],check=True)
    spec=importlib.util.spec_from_file_location('makos_package_base',ROOT/'build.py')
    b=importlib.util.module_from_spec(spec);sys.modules[spec.name]=b;spec.loader.exec_module(b)
    b.DIST=ROOT/'dist/makos'
    b.STAGE=b.DIST/'stage';b.PKG_DIR=b.DIST/'packages';b.APT_DIR=b.DIST/'apt';b.SUITE='makos-testing'
    spec=importlib.util.spec_from_file_location('makos_builder',ROOT/'tools/builders/makos.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    builders=module.register(b)
    debs=[]
    names=args.only.split(',') if args.only else list(builders)
    for name in names:
        if name not in builders:parser.error('Unknown MakOS package: '+name)
        deb=builders[name]().build();debs.append(deb)
        print('Built',deb.name,deb.stat().st_size,flush=True)
    if not args.no_repo:
        # Use the existing signing service through gpg; never read/copy private key material.
        b.make_repo(sorted(b.PKG_DIR.glob('*.deb')))
    return 0
if __name__=='__main__':sys.exit(main())
