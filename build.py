#!/usr/bin/env python3
"""VigilOS Debian packaging, adapted from the tested GPL Amerika package builder."""
import datetime
import gzip
import hashlib
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'src'
DIST=ROOT/'dist/makos'
STAGE=DIST/'stage'
PKG_DIR=DIST/'packages'
APT_DIR=DIST/'apt'
SIGN_HOME=Path(os.environ.get('MAKOS_SIGNING_HOME',Path.home()/'.local/share/amerika-os-signing'))
KEY_NAME=os.environ.get('MAKOS_SIGNING_IDENTITY','Amerika OS Archive Signing Key')
ARCH='arm64'
SUITE='makos-testing'
MAINTAINER='VigilTech <noreply@users.noreply.github.com>'
HOMEPAGE='https://vigiltech.org'


def sh(*args, **kw):
    kw.setdefault('check', True)
    return subprocess.run([str(a) for a in args], **kw)

def write(path, text, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)

def copy(src, dst, mode=None):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if mode is not None:
        dst.chmod(mode)

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

class Pkg:
    def __init__(self, name, version, description, arch='all', depends='', title=None, category='System',
                 section='x11', homepage=HOMEPAGE, extra=None, recommends='', provides='', conflicts=''):
        self.name, self.version, self.arch = name, version, arch
        self.description, self.depends, self.title, self.category = description, depends, title, category
        self.section, self.homepage, self.extra = section, homepage, extra or {}
        self.recommends, self.provides, self.conflicts = recommends, provides, conflicts
        self.root = STAGE / name
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.scripts = {}

    def path(self, p):
        return self.root / str(p).lstrip('/')

    def file(self, dest, text, mode=0o644):
        write(self.path(dest), text, mode)

    def copy(self, src, dest, mode=None):
        copy(src, self.path(dest), mode)

    def copyright(self, text):
        self.file(f'/usr/share/doc/{self.name}/copyright', text)

    def build(self):
        size = sum(f.stat().st_size for f in self.root.rglob('*') if f.is_file()) // 1024
        lines = [f'Package: {self.name}', f'Version: {self.version}', f'Architecture: {self.arch}',
                 f'Maintainer: {MAINTAINER}', f'Installed-Size: {size}', f'Section: {self.section}',
                 'Priority: optional', f'Homepage: {self.homepage}']
        for key, val in (('Depends', self.depends), ('Recommends', self.recommends), ('Provides', self.provides),
                         ('Conflicts', self.conflicts)):
            if val:
                lines.append(f'{key}: {val}')
        if self.title:
            lines.append(f'MakOS-Title: {self.title}')
        lines.append(f'MakOS-Category: {self.category}')
        for k, v in self.extra.items():
            lines.append(f'{k}: {v}')
        desc = self.description.strip().split('\n')
        lines.append('Description: ' + desc[0])
        for extra in desc[1:]:
            lines.append(' ' + (extra.strip() or '.'))
        write(self.root / 'DEBIAN/control', '\n'.join(lines) + '\n')
        for name, text in self.scripts.items():
            write(self.root / 'DEBIAN' / name, text, 0o755)
        conffiles = [('/'+str(f.relative_to(self.root))) for f in sorted(self.root.glob('etc/**/*')) if f.is_file() and not f.is_symlink()]
        if conffiles:
            write(self.root / 'DEBIAN/conffiles', '\n'.join(conffiles) + '\n')
        # md5sums for dpkg --verify
        sums = []
        for f in sorted(self.root.rglob('*')):
            if f.is_file() and not f.is_symlink() and 'DEBIAN' not in f.relative_to(self.root).parts:
                h = hashlib.md5(f.read_bytes()).hexdigest()
                sums.append(f'{h}  {f.relative_to(self.root)}')
        write(self.root / 'DEBIAN/md5sums', '\n'.join(sums) + '\n')
        PKG_DIR.mkdir(parents=True, exist_ok=True)
        out = PKG_DIR / f'{self.name}_{self.version}_{self.arch}.deb'
        out.unlink(missing_ok=True)
        zopt = ['-Zzstd', '-z10'] if size > 20000 else ['-Zxz', '-z6']
        sh('dpkg-deb', '--root-owner-group', *zopt, '--build', self.root, out, stdout=subprocess.DEVNULL)
        return out

def gpg(*args, **kw):
    env = dict(os.environ, GNUPGHOME=str(SIGN_HOME))
    return sh('gpg', '--batch', '--yes', '--no-tty', *args, env=env, **kw)

def deb_fields(deb):
    return sh('dpkg-deb', '-f', deb, capture_output=True, text=True).stdout.strip()

def make_repo(debs):
    if APT_DIR.exists():
        shutil.rmtree(APT_DIR)
    entries = []
    for deb in sorted(debs):
        fields = deb_fields(deb)
        name = re.search(r'^Package: (.+)$', fields, re.M).group(1)
        letter = name[0]
        rel = f'pool/main/{letter}/{name}/{deb.name}'
        dest = APT_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(deb, dest)
        entries.append(f'{fields}\nFilename: {rel}\nSize: {dest.stat().st_size}\nSHA256: {sha256(dest)}\n')
    pkgdir = APT_DIR / f'dists/{SUITE}/main/binary-{ARCH}'
    pkgdir.mkdir(parents=True)
    text = '\n'.join(entries).encode()
    (pkgdir / 'Packages').write_bytes(text)
    (pkgdir / 'Packages.gz').write_bytes(gzip.compress(text, 9, mtime=0))
    (pkgdir / 'Packages.xz').write_bytes(lzma.compress(text))
    rel_files = {}
    for f in sorted((APT_DIR / f'dists/{SUITE}').rglob('*')):
        if f.is_file():
            rel_files[str(f.relative_to(APT_DIR / f'dists/{SUITE}'))] = f
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S UTC')
    lines = ['Origin: VigilOS', 'Label: VigilOS', f'Suite: {SUITE}', f'Codename: {SUITE}', f'Date: {now}',
             f'Architectures: {ARCH}', 'Components: main', 'Description: VigilOS development packages', 'SHA256:']
    for rel, f in rel_files.items():
        lines.append(f' {sha256(f)} {f.stat().st_size:>16} {rel}')
    release = APT_DIR / f'dists/{SUITE}/Release'
    release.write_text('\n'.join(lines) + '\n')
    gpg('--local-user', KEY_NAME, '--armor', '--detach-sign', '--output', str(release) + '.gpg', str(release))
    gpg('--local-user', KEY_NAME, '--clearsign', '--output', str(release.parent / 'InRelease'), str(release))
    gpg('--export', '--output', str(APT_DIR / 'makos-archive-keyring.gpg'), KEY_NAME)
    gpg('--armor', '--export', '--output', str(APT_DIR / 'makos-archive-keyring.asc'), KEY_NAME)
    fp = gpg('--with-colons', '--fingerprint', KEY_NAME, capture_output=True, text=True).stdout
    fingerprint = re.search(r'^fpr:+([0-9A-F]{40}):', fp, re.M).group(1)
    manifest = {'suite': SUITE, 'architecture': ARCH, 'fingerprint': fingerprint,
                'generated': now, 'packages': {}}
    for deb in sorted(APT_DIR.glob('pool/main/*/*/*.deb')):
        manifest['packages'][deb.name] = {'path': str(deb.relative_to(APT_DIR)), 'size': deb.stat().st_size,
                                          'sha256': sha256(deb)}
    (APT_DIR / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Repository written to', APT_DIR, 'key', fingerprint)

if __name__=='__main__':
    from tools.build_makos import main
    sys.exit(main())
