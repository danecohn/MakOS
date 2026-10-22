"""Desktop wallpaper: built-in images shipped with MakOS, the user's own pictures, and the choice stored in settings.json."""
import os
from pathlib import Path

from .. import common
from . import look

IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp')
DEFAULT_NAME = 'wallpaper-aurora-blue.png'
MAX_BYTES = 80_000_000


def builtin():
    base = common.SHARE / 'wallpapers'
    try:
        return sorted(p for p in base.iterdir() if p.suffix.lower() in IMAGE_EXT and p.is_file() and not p.name.startswith('.'))
    except OSError:
        return []


def user_dirs():
    pictures = Path(os.environ.get('XDG_PICTURES_DIR') or Path.home() / 'Pictures')
    return [pictures / 'Wallpapers', pictures, common.CONFIG / 'wallpapers']


def user_images(limit=60):
    out = []
    for d in user_dirs():
        try:
            for p in sorted(d.iterdir()):
                if p.is_file() and p.suffix.lower() in IMAGE_EXT and not p.name.startswith('.') and p.stat().st_size <= MAX_BYTES:
                    out.append(p)
        except OSError:
            continue
    return out[:limit]


def check(value):
    p = Path(value)
    if not p.is_absolute() or p.suffix.lower() not in IMAGE_EXT or not p.is_file():
        raise ValueError('Choose a PNG, JPEG or WebP image.')
    if p.stat().st_size > MAX_BYTES:
        raise ValueError('That image is larger than 80 MB.')
    return str(p)


def set_wallpaper(value):
    return look.put(wallpaper=check(value) if value else '')


def current(data=None):
    """The image the shell should show: the chosen file when it still exists, else the shipped default, else None."""
    data = data or common.load_settings()
    chosen = data.get('wallpaper') or ''
    if chosen and Path(chosen).is_file():
        return Path(chosen)
    default = common.SHARE / 'wallpapers' / DEFAULT_NAME
    return default if default.exists() else None
