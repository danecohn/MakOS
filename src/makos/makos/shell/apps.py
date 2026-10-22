"""Window identity adapters; MakOS launch policy lives in its curated catalog."""
from gi.repository import Gio

def lookup(desktop_id):
    try:
        return Gio.DesktopAppInfo.new(desktop_id if desktop_id.endswith('.desktop') else desktop_id + '.desktop')
    except TypeError:
        return None

def identity(info):
    if info is None:
        return set()
    return {info.get_id().removesuffix('.desktop').lower(), (info.get_startup_wm_class() or '').lower(),
            (info.get_executable() or '').rsplit('/', 1)[-1].lower()}
