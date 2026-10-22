"""Application switcher semantics (pure Python, no GTK).

* Meta+Tab cycles *applications*, most recently used first; each application is one entry that groups all of its windows.
* Meta+Shift+Tab reverses. Q quits and H hides the selected application while the switcher is open.
* Meta+` cycles the *windows* of the active application in a fixed ring order.
"""
from dataclasses import dataclass, field

from . import launcher


@dataclass
class AppGroup:
    key: str
    name: str
    icon: str
    windows: list = field(default_factory=list)   # most recent first
    mru: int = 0
    hidden: bool = False                           # every window minimized

    def window_ids(self):
        return [str(w['id']) for w in self.windows]


def app_groups(windows, desktop=None):
    """Applications that have windows, most recently used first. `desktop` limits to windows on that desk (plus
    windows on all desks); minimized windows still count so a hidden app can be brought back."""
    visible = []
    for w in windows:
        if not w.get('normal', True) or w.get('skip'):
            continue
        desks = w.get('desktops') or []
        if desktop is not None and desks and desktop not in desks:
            continue
        visible.append(w)
    groups = []
    for key, wins in launcher.windows_by_group(visible).items():
        rec = launcher.catalog.BY_ID.get(key)
        groups.append(AppGroup(key, rec.name if rec else launcher.display_name(wins[0]), rec.icon if rec else '', wins,
                               max(int(w.get('mru', 0)) for w in wins), all(w.get('minimized') for w in wins)))
    groups.sort(key=lambda g: -g.mru)
    return groups


class AppSwitcher:
    """State of one Meta+Tab session."""

    def __init__(self, groups):
        self.groups = list(groups)
        # the first press moves to the previous application (index 1); with one application there is nothing to leave
        self.index = 1 if len(self.groups) > 1 else 0

    @property
    def selected(self):
        return self.groups[self.index] if self.groups else None

    def next(self):
        if self.groups:
            self.index = (self.index + 1) % len(self.groups)
        return self.selected

    def prev(self):
        if self.groups:
            self.index = (self.index - 1) % len(self.groups)
        return self.selected

    def remove_selected(self):
        """After quitting/hiding the selected app drop it; selection moves to the next entry."""
        if not self.groups:
            return None
        del self.groups[self.index]
        if self.groups:
            self.index = min(self.index, len(self.groups) - 1)
        return self.selected

    def target_window(self):
        """Window to raise when the switcher commits: the most recent window of the selected app."""
        g = self.selected
        return g.windows[0] if g and g.windows else None


def next_window_in_app(windows, active_id, reverse=False):
    """Meta+`: the next window of the same application as `active_id` in a stable ring order (by id). None if the
    application has fewer than two windows."""
    active = next((w for w in windows if str(w.get('id')) == str(active_id)), None)
    if not active:
        return None
    key = launcher.group_key(active)
    ring = sorted((w for w in windows if w.get('normal', True) and not w.get('skip') and launcher.group_key(w) == key),
                  key=lambda w: str(w['id']))
    if len(ring) < 2:
        return None
    i = [str(w['id']) for w in ring].index(str(active_id))
    return ring[(i + (-1 if reverse else 1)) % len(ring)]
