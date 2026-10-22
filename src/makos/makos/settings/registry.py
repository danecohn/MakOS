"""The list of Settings panes. Pure data (no GTK) so Seek, tests and the shell can use it without a display.

Every pane has a distinct icon name. `ICON` names are looked up by makos.ui.icon(): first an AI-generated PNG under
icons/MakkOS/128x128/apps/<name>.png, then the theme icon 'makos-<name>' (the original vector fallback made by
tools/make_makos_vectors.py). See docs/makos/settings.md for which are still vector fallbacks awaiting regenerated art.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Pane:
    id: str
    title: str
    group: str
    icon: str
    keywords: tuple
    module: str


def _p(id_, title, group, keywords, module=None):
    return Pane(id_, title, group, 'pane-' + id_, tuple(keywords.split()), module or 'pane_' + id_)


PANES = [
    _p('appearance', 'Appearance', 'Personal', 'accent colour color graphite font text size scroll bars transparency motion pinstripes theme'),
    _p('desktop', 'Desktop & Screen Saver', 'Personal', 'wallpaper background picture screen saver lock idle timeout'),
    _p('launcher', 'Launcher Bar', 'Personal', 'dock launcher size magnification position autohide recents icons'),
    _p('desks', 'Desks & Spread', 'Personal', 'hot corners shortcuts desktops spaces spread mission control'),
    _p('language', 'Language & Text', 'Personal', 'language region locale keyboard layout input text replacement formats'),
    _p('security', 'Security', 'Personal', 'privacy firewall lock password screen camera microphone location permissions'),
    _p('displays', 'Displays', 'Hardware', 'resolution scale rotation arrangement night shift night light monitor screen brightness'),
    _p('keyboard', 'Keyboard', 'Hardware', 'repeat rate delay shortcuts modifier caps lock keys'),
    _p('mouse', 'Mouse & Trackpad', 'Hardware', 'tap click natural scroll speed gestures touchpad pointer acceleration'),
    _p('sound', 'Sound', 'Hardware', 'volume output input microphone speakers headphones balance apps'),
    _p('energy', 'Energy Saver', 'Hardware', 'battery power profile lid sleep charge limit health'),
    _p('printers', 'Printers', 'Hardware', 'printer cups print queue test page'),
    _p('bluetooth', 'Bluetooth', 'Internet & Wireless', 'bluetooth pair connect devices headphones'),
    _p('network', 'Network', 'Internet & Wireless', 'wifi wi-fi wireless ethernet vpn proxy dns internet'),
    _p('sharing', 'Sharing', 'Internet & Wireless', 'sharing remote login ssh file sharing samba rdp'),
    _p('users', 'Users', 'System', 'account user name picture password login'),
    _p('datetime', 'Date & Time', 'System', 'clock time zone ntp 24 hour'),
    _p('update', 'Software Update', 'System', 'updates apt upgrade packages security'),
    _p('accessibility', 'Accessibility', 'System', 'large text contrast reduce motion sticky keys screen reader zoom'),
    _p('startup', 'Startup', 'System', 'login items autostart boot theme'),
    _p('rewind', 'Rewind', 'System', 'backup restore snapshot time machine'),
]
BY_ID = {p.id: p for p in PANES}
BY_TITLE = {p.title.lower(): p for p in PANES}
GROUPS = []
for _p_ in PANES:
    if not GROUPS or GROUPS[-1][0] != _p_.group:
        GROUPS.append((_p_.group, []))
    GROUPS[-1][1].append(_p_)


def find(name):
    """Pane by id or title (case-insensitive); None if unknown."""
    key = (name or '').strip().lower()
    return BY_ID.get(key) or BY_TITLE.get(key)


def search(query):
    """Panes whose title or keywords contain every word of the query, best title matches first."""
    words = (query or '').lower().split()
    if not words:
        return []
    scored = []
    for p in PANES:
        hay_title = p.title.lower()
        hay = hay_title + ' ' + ' '.join(p.keywords)
        if all(w in hay for w in words):
            scored.append((0 if all(w in hay_title for w in words) else 1, p.title, p))
    return [p for _s, _t, p in sorted(scored, key=lambda t: t[:2])]


# Keys of settings.json the running shell acts on (checked by the panes to decide whether to say "saved" or "applied").
SHELL_HONORS = {'launcher_size': True, 'launcher_position': True, 'launcher_autohide': True, 'launcher_magnify': True,
                'launcher_magnify_percent': True, 'wallpaper': True, 'reduce_motion': True, 'pinstripes': True,
                'accent': True, 'font_size': True, 'scrollbars': True, 'reduce_transparency': True, 'text_scale': True,
                'high_contrast': True, 'launcher_recents': False, 'privacy_indicators': False, 'clock_24h': False}
