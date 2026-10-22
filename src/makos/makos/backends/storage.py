"""Storage backend: mounted file systems (df) and where the home folder's space goes (du)."""
import os
from pathlib import Path

from . import sysutil

REAL_FS = ('ext4', 'ext3', 'btrfs', 'xfs', 'f2fs', 'vfat', 'ntfs', 'ntfs3', 'exfat', 'fuseblk', 'zfs')
HOME_PARTS = [('Documents', 'Documents'), ('Downloads', 'Downloads'), ('Pictures', 'Pictures'), ('Videos', 'Videos'), ('Music', 'Music'),
              ('Desktop', 'Desktop'), ('.cache', 'Caches'), ('.local/share/Trash', 'Trash')]


def human(n):
    n = float(n)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1000


def volumes():
    res = sysutil.run(['df', '-B1', '--output=source,fstype,size,used,avail,target'], timeout=8)
    out, seen = [], set()
    for line in res.out.splitlines()[1:]:
        f = line.split(None, 5)
        if len(f) < 6 or f[1] not in REAL_FS or f[0] in seen:
            continue
        if f[5].startswith(('/snap', '/var/lib/docker', '/run')):
            continue
        seen.add(f[0])
        size, used, avail = int(f[2]), int(f[3]), int(f[4])
        out.append({'device': f[0], 'fstype': f[1], 'size': size, 'used': used, 'free': avail, 'mount': f[5],
                    'percent': round(100 * used / size) if size else 0})
    return out


def home_usage(home=None, timeout=25):
    home = Path(home or Path.home())
    out = []
    for rel, title in HOME_PARTS:
        p = home / rel
        if not p.exists():
            continue
        res = sysutil.run(['du', '-sb', '--', str(p)], timeout=timeout)
        if res.code == 0 and res.out.split():
            try:
                out.append({'name': title, 'path': str(p), 'bytes': int(res.out.split()[0])})
            except ValueError:
                pass
    return sorted(out, key=lambda e: -e['bytes'])


def free_in_home():
    try:
        st = os.statvfs(Path.home())
        return {'free': st.f_bavail * st.f_frsize, 'total': st.f_blocks * st.f_frsize}
    except OSError:
        return {'free': 0, 'total': 0}
