"""Settings rig: every pane is built in a real GTK window under a private KWin, first against tests/fakesys.py (deterministic
screenshots and verified apply paths), then read-only against the real services. Run through makos_settings_rig.sh."""
import json
import os
import sys
import traceback
from pathlib import Path

from makos_rig_common import OUT, find_all, settle, shot, spin, texts  # isort: skip
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, Gtk  # noqa: E402
from PIL import Image  # noqa: E402

from fakesys import FakeSystem  # noqa: E402
from makos import common, ui  # noqa: E402
from makos.backends import sysutil  # noqa: E402
from makos.settings import registry  # noqa: E402
from makos.settings.app import Settings  # noqa: E402

HOME = Path.home()
CFG = Path(os.environ['XDG_CONFIG_HOME'])
failures = []


def check(cond, message):
    if not cond:
        failures.append(message)
        print('FAIL:', message, flush=True)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.makos.RigSettings', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.reloads = 0

    def reload_preferences(self):
        self.reloads += 1


app = App()
app.register(None)
app.hold()
ui.install_theme()

# ---- fixtures: wallpapers, a login item, a shortcut conflict, a user vCard
for i, colour in enumerate(((40, 90, 160), (30, 120, 90), (140, 70, 60))):
    Image.new('RGB', (640, 400), colour).save(HOME / f'Pictures/Wallpapers/rig-{i}.png')
(CFG / 'autostart').mkdir(parents=True, exist_ok=True)
(CFG / 'autostart/syncthing.desktop').write_text('[Desktop Entry]\nType=Application\nName=File Sync\nExec=syncthing serve --no-browser\n')
comp = CFG / 'makos/compositor'
comp.mkdir(parents=True, exist_ok=True)
(comp / 'kglobalshortcutsrc').write_text('[kwin]\nMakOS: Seek=Meta+Space,Meta+Space,Seek\n[other]\nlaunch calculator=Meta+F10,none,Calc\n')

fake = FakeSystem()
sysutil.set_runner(fake, fake.which)
settings = Settings(app)
settings.win.set_default_size(840, 980)
settle(.8)
check(settings.stack.get_visible_child_name() == 'all', 'grid should be the first page')
shot(settings.win, '00-grid')
check(len(settings.tiles) == len(registry.PANES) == 21, 'every pane has a tile')

# ---- build every pane against the fake system
for p in registry.PANES:
    try:
        settings.pane(p.id)
        settle(.9)
        page = settings.stack.get_visible_child()
        check(settings.current == p.id, f'{p.id}: pane did not open')
        body = ' '.join(texts(page))
        check('could not be loaded' not in body, f'{p.id}: pane failed to load: {body[:200]}')
        check('This information is not available' not in body, f'{p.id}: a loader failed: {body[:200]}')
        shot(settings.win, f'pane-{p.id}')
    except Exception:
        failures.append(f'{p.id}: exception')
        traceback.print_exc()
        print('FAIL: exception in', p.id, flush=True)

# ---- behaviour: widgets really change settings through the backends
def pane(pid):
    settings.pane(pid)
    settle(.9)
    return settings.stack.get_visible_child()


page = pane('appearance')
dd = [d for d in find_all(page, Gtk.DropDown)][0]
dd.set_selected(3)  # green
spin(lambda: common.load_settings()['accent'] == 'green')
check(app.reloads > 0, 'changing a shell-visible setting asks the shell to reload')
sw = find_all(page, Gtk.Switch)
sw[1].set_active(True)  # reduce transparency
spin(lambda: common.load_settings()['reduce_transparency'] is True)

page = pane('launcher')
scales = find_all(page, Gtk.Scale)
scales[0].set_value(80)
spin(lambda: common.load_settings()['launcher_size'] == 80, 4)
find_all(page, Gtk.DropDown)[0].set_selected(1)
spin(lambda: common.load_settings()['launcher_position'] == 'left')

page = pane('desks')
find_all(page, Gtk.DropDown)[0].set_selected(3)  # top-left -> spread
spin(lambda: fake.config.get(('kwinrc', 'Script-makos-bridge', 'HotTopLeft')) == 'spread')
check(any('loadScript' in ' '.join(c) for c in fake.calls), 'bridge script reloaded for hot corners')
find_all(page, Gtk.Scale)[0].set_value(6)
spin(lambda: fake.config.get(('kwinrc', 'Desktops', 'Number')) == '6', 4)

page = pane('keyboard')
find_all(page, Gtk.Scale)[0].set_value(400)
spin(lambda: fake.config.get(('kcminputrc', 'Keyboard', 'RepeatDelay')) == '400', 4)

page = pane('security')
fw = find_all(page, Gtk.Switch)[2]  # auto lock, lock on resume, firewall, privacy indicators
fw.set_active(True)
spin(lambda: fake.pkexec_calls and fake.pkexec_calls[-1][1] == 'firewall-enable')

page = pane('sound')
find_all(page, Gtk.Scale)[0].set_value(42)
spin(lambda: any(c[:2] == ['pactl', 'set-sink-volume'] and c[-1] == '42%' for c in fake.calls), 4)

page = pane('mouse')
mouse_switches = find_all(page, Gtk.Switch)
mouse_switches[1].set_active(False)  # natural scroll
spin(lambda: fake.pointer['naturalScroll'] is False)

page = pane('accessibility')
find_all(page, Gtk.Switch)[0].set_active(True)  # increase contrast
spin(lambda: common.load_settings()['high_contrast'] is True)
shot(settings.win, 'accessibility-contrast')
find_all(page, Gtk.Switch)[0].set_active(False)
spin(lambda: common.load_settings()['high_contrast'] is False)

page = pane('language')
entries = find_all(page, Gtk.Entry)
entries[-2].set_text('omw')
entries[-1].set_text('on my way')
[b for b in find_all(page, Gtk.Button) if b.get_label() == 'Add'][0].emit('clicked')
spin(lambda: common.load_settings()['text_replacements'] == [['omw', 'on my way']])

page = pane('update')
btn = [b for b in find_all(page, Gtk.Button) if b.get_label() == 'Check Now'][0]
btn.emit('clicked')
spin(lambda: fake.pkexec_calls and fake.pkexec_calls[-1][1] == 'apt-update', 4)

page = pane('startup')
def switch_for(page, label):
    for sw in find_all(page, Gtk.Switch):
        row = sw.get_parent()
        for _ in range(3):
            if row is not None and label in texts(row):
                return sw
            row = row.get_parent() if row is not None else None
    raise AssertionError('no switch for %s in %s' % (label, texts(page)))


switch_for(page, 'File Sync').set_active(False)
spin(lambda: 'Hidden=true' in (CFG / 'autostart/syncthing.desktop').read_text())

# ---- larger text must not clip the grid: scale fonts up and screenshot the grid
settings.show_all()
from makos.backends import accessibility  # noqa: E402
accessibility.set_text_scale(1.5)
settings.ctx.changed()
settle(.8)
shot(settings.win, 'grid-large-text')
accessibility.set_text_scale(1.0)
settings.ctx.changed()

# ---- real services, read only (nothing is written): panes must build against whatever this machine has
sysutil.set_runner(None)
for pid in ('displays', 'sound', 'energy', 'update', 'datetime', 'sharing', 'printers', 'rewind', 'startup', 'bluetooth', 'network', 'users', 'security'):
    try:
        page = pane(pid)
        body = ' '.join(texts(page))
        check('could not be loaded' not in body, f'real {pid}: {body[:160]}')
        if pid in ('displays', 'energy', 'update', 'rewind', 'startup'):
            shot(settings.win, f'real-{pid}')
    except Exception:
        failures.append(f'real {pid}: exception')
        traceback.print_exc()
from makos.backends import displays  # noqa: E402
real = displays.outputs()
print('REAL KWIN OUTPUTS:', json.dumps([{k: o[k] for k in ('name', 'scale', 'width', 'height')} for o in real]), flush=True)

settings.win.destroy()
if failures:
    print('SETTINGS RIG FAILED:', failures, flush=True)
    sys.exit(1)
print('SETTINGS RIG PASS: %d panes built with fixtures, behaviour checks applied through backends, real read-only panes built' % len(registry.PANES), flush=True)
