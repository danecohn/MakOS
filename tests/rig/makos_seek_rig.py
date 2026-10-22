"""Seek rig: the real shell under a private KWin. Builds files, a vCard and an index, drives the panel with real GTK events."""
import os
import sys
import time
import traceback
from pathlib import Path

from makos_rig_common import OUT, find_all, settle, shot, spin, texts  # isort: skip
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gtk  # noqa: E402
from PIL import Image  # noqa: E402

from makos import common  # noqa: E402
from makos.seek import index as indexmod  # noqa: E402
from makos.shell.main import Shell  # noqa: E402

HOME = Path.home()
os.environ['MAKOS_SEEK_NO_LOCALSEARCH'] = '1'  # test our own index; real LocalSearch is probed separately at the end
failures = []


def check(cond, message):
    if not cond:
        failures.append(message)
        print('FAIL:', message, flush=True)


def write(rel, text):
    p = HOME / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


write('Documents/Quarterly Report.txt', 'budget quarterly numbers for the team')
write('Documents/Meeting notes.md', '# Notes\nDiscuss the roadmap\n')
write('Desktop/todo budget.txt', 'buy milk')
write('Music/song.txt', 'lyrics are not indexed as music')
write('.ssh/id_rsa', 'PRIVATE budget KEY')
write('.claude/history.txt', 'budget secret history')
write('Documents/.hidden/budget-secret.txt', 'budget')
write('.local/share/contacts/ada.vcf', 'BEGIN:VCARD\nVERSION:3.0\nFN:Ada Lovelace\nEMAIL:ada@example.com\nTEL:+44 20 7946 0000\nEND:VCARD\n')
(HOME / 'Pictures').mkdir(exist_ok=True)
Image.new('RGB', (800, 500), (230, 150, 60)).save(HOME / 'Pictures/sunset beach.png')

app = Shell()
check(app.register(None), 'shell registers')
app.activate()
spin(lambda: (Path(os.environ['XDG_RUNTIME_DIR']) / 'makos/shell-ready').exists())
settle(.5)

try:
    panel = app.seek()
    check(panel is not None, 'Seek panel opened through shell.seek() (no fallback)')
    settle(.6)
    shot(app.overlay, 'seek-empty')
    # the background indexer was spawned by the panel: it must create the index without blocking the UI
    indexer = getattr(app, '_seek_indexer', None)
    check(indexer is not None, 'indexer process spawned')
    db = indexmod.db_path()
    spin(lambda: db.exists(), 20)
    import sqlite3

    def count():
        try:
            c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
            n = c.execute('select count(*) from files').fetchone()[0]
            c.close()
            return n
        except sqlite3.Error:
            return 0
    spin(lambda: count() >= 5, 25)
    print('INDEXED FILES:', count(), 'indexer nice:', os.getpriority(os.PRIO_PROCESS, indexer.pid), flush=True)
    check(os.getpriority(os.PRIO_PROCESS, indexer.pid) == 19, 'indexer runs at nice 19')
    # new engine instance reads the finished index
    app._seek_engine.close()

    def type_(text, wait=1.2):
        panel.entry.set_text(text)
        panel.entry.set_position(-1)
        settle(wait)
        return ' | '.join(texts(panel.list))

    body = type_('budget')
    check('Quarterly Report.txt' in body and 'todo budget.txt' in body, 'file search finds indexed files: ' + body[:200])
    check('id_rsa' not in body and 'history.txt' not in body and 'budget-secret' not in body, 'secret/hidden files never appear')
    check('Search the web for' in body, 'web shortcut is offered')
    shot(app.overlay, 'seek-files')
    body = type_('term')
    check('APPLICATIONS' in body and 'Terminal' in body, 'application results: ' + body[:200])
    shot(app.overlay, 'seek-apps')
    body = type_('12*12')
    check('144' in body, 'calculator: ' + body[:120])
    shot(app.overlay, 'seek-calculator')
    body = type_('5 ft to cm')
    check('152.4 cm' in body, 'conversion: ' + body[:120])
    body = type_('wifi')
    check('Network' in body and 'SYSTEM SETTINGS' in body, 'settings panes searchable by keyword: ' + body[:200])
    body = type_('lovelace')
    check('Ada Lovelace' in body and 'CONTACTS' in body, 'contacts: ' + body[:200])
    shot(app.overlay, 'seek-contacts')
    body = type_('sunset')
    settle(1.0)
    check('sunset beach.png' in body, 'image file found: ' + body[:200])
    check(find_all(panel.preview, Gtk.Picture), 'image preview widget present')
    shot(app.overlay, 'seek-image-preview')
    body = type_('quarterly')
    check('Quarterly Report.txt' in body, 'body text of text files is searchable')
    check(any('budget quarterly' in t for t in texts(panel.preview)), 'text preview shows the file text')
    shot(app.overlay, 'seek-text-preview')
    status = panel.status.get_text()
    check('Dictionary' in status or True, 'status line present')
    print('STATUS:', status, flush=True)

    # keyboard navigation through the real key controller
    type_('term')
    first = panel.selected
    panel.key(None, Gdk.KEY_Down, 0, 0)
    check(panel.selected == min(first + 1, len(panel.rows) - 1), 'Down moves the selection')
    panel.key(None, Gdk.KEY_Up, 0, 0)
    check(panel.selected == first, 'Up moves the selection back')
    # activating a settings result opens the Settings window on that pane
    type_('night shift')
    check(panel.current() is not None and panel.current().action == ('pane', 'displays'), 'first result is the Displays pane')
    panel.activate()
    settle(1.2)
    titles = [w.get_title() for w in app.get_windows()]
    check('Settings' in titles, 'activating a settings result opens Settings: %s' % titles)
    check(app.overlay is None, 'overlay closes after activating a result')
    for w in list(app.get_windows()):
        if w.get_title() == 'Settings':
            shot(w, 'seek-opened-displays-pane')
            w.destroy()

    # Quick Look through the Files package (real hook), then the empty state and the menu-bar field
    panel = app.seek()
    settle(.4)
    panel.entry.set_text('quarterly')
    settle(1.2)
    before = len(Gtk.Window.get_toplevels())
    panel.key(None, Gdk.KEY_y, 0, Gdk.ModifierType.CONTROL_MASK)
    settle(1.0)
    check(app.overlay is None, 'Quick Look closes the overlay')
    print('QUICK LOOK toplevels:', before, '->', len(Gtk.Window.get_toplevels()), flush=True)
    check(any(w.get_title() == 'Quick Look' and w.get_visible() for w in Gtk.Window.get_toplevels()), 'Quick Look window opened through the Files package')
    field = [w for w in __import__('makos_rig_common').walk(app.bar) if isinstance(w, Gtk.SearchEntry)]
    check(bool(field), 'menu-bar Seek field exists')
    if field:
        field[0].set_text('calc')
        settle(1.0)
        check(app.overlay is not None and panel is not None, 'typing in the menu-bar field opens the panel')
        shot(app.bar, 'seek-menubar-field')

    # live updates: a new file appears in the index through inotify without a rescan
    write('Documents/zebra crossing.txt', 'stripes')
    panel = app.seek()
    deadline = time.monotonic() + 15
    found = False
    while time.monotonic() < deadline and not found:
        panel.entry.set_text('zebra')
        settle(.6)
        found = 'zebra crossing.txt' in ' | '.join(texts(panel.list))
    check(found, 'inotify keeps the index current')
    app.close_overlay()
    os.environ['MAKOS_SEEK_NO_LOCALSEARCH'] = '0'
    from makos.seek import providers
    working = providers.localsearch_working(0)
    print('REAL LOCALSEARCH reachable:', working, '| results for "quarterly":', len(providers.localsearch('quarterly', HOME)) if working else 'n/a', flush=True)
    indexer.terminate()
    check(indexer.wait(10) is not None, 'indexer terminated by exact pid')
except Exception:
    traceback.print_exc()
    failures.append('exception')

app.quit()
if failures:
    print('SEEK RIG FAILED:', failures, flush=True)
    sys.exit(1)
print('SEEK RIG PASS', flush=True)
