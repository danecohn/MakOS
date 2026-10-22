"""Helpers for the launcher-and-windows rig checks (run inside makos_launcher_rig.sh's private session)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / 'dist/makos/rig-launcher'
sys.path.insert(0, str(Path(__file__).parent))

os.environ.setdefault('MAKOS_SHARE', str(ROOT / 'src/makos'))
os.environ.setdefault('MAKOS_RIG_SHOTS', str(SHOTS))
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
procs = []   # (name, Popen): children this run started; cleaned by exact PID only


def sh_env():
    env = dict(os.environ)
    env['PYTHONPATH'] = f"{ROOT / 'src/makos'}:{ROOT / 'src/os'}"
    env['MAKOS_SHARE'] = str(ROOT / 'src/makos')
    env['MAKOS_RIG_SHOTS'] = str(SHOTS)
    env['GTK_A11Y'] = 'none'
    env['MAKOS_LAYERSHELL_LIB'] = os.environ.get('AMERIKA_LAYERSHELL_LIB', '/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0')
    return env


def start_shell(extra_env=None):
    SHOTS.mkdir(parents=True, exist_ok=True)
    env = sh_env()
    env.update(extra_env or {})
    log = open(os.environ['T'] + '/makos-shell.log', 'w')
    argv = [str(ROOT / 'src/makos/bin/makos-shell')]
    if os.environ.get('MAKOS_GDB'):   # debugging aid: break on a GTK/pixman error and print the C backtrace
        env['MAKOS_GDB_LD_PRELOAD'] = env.get('LD_PRELOAD', '') or env['MAKOS_LAYERSHELL_LIB']
        argv = ['gdb', '-batch', '-ex', 'set environment LD_PRELOAD ' + env['MAKOS_LAYERSHELL_LIB'], '-ex', 'set breakpoint pending on',
                '-ex', 'break pixman_region32_init_rect if (int)$x3 < 0 || (int)$x4 < 0', '-ex', 'run', '-ex', 'bt 25', '-ex', 'kill',
                '--args', sys.executable, '-m', 'makos.shell.main']
        env.pop('LD_PRELOAD', None)
    p = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
    procs.append(('shell', p))
    ready = Path(os.environ['XDG_RUNTIME_DIR']) / 'makos/shell-ready'
    end = time.monotonic() + 25
    while not ready.exists():
        if p.poll() is not None:
            raise RuntimeError('shell exited:\n' + Path(os.environ['T'] + '/makos-shell.log').read_text())
        if time.monotonic() > end:
            raise RuntimeError('shell never became ready')
        time.sleep(0.1)
    return p


def control(action):
    bus.call_sync('org.makos.Shell', '/Control', 'org.makos.Control', 'Action', GLib.Variant('(s)', (action,)), None, Gio.DBusCallFlags.NONE, 15000, None)


def state():
    r = bus.call_sync('org.makos.Shell', '/Control', 'org.makos.Control', 'State', None, None, Gio.DBusCallFlags.NONE, 15000, None)
    return json.loads(r.unpack()[0])


def windows():
    return state()['windows'].get('windows', [])


def spawn_window(app_id, title, color='#3b6fb6', size=(640, 420), extra=None):
    """A plain GTK window with its own application id (so KWin reports it as that application)."""
    env = sh_env()
    env.pop('LD_PRELOAD', None)
    p = subprocess.Popen([sys.executable, str(Path(__file__).parent / 'makos_launcher_window.py'), app_id, title, color, str(size[0]), str(size[1])] + (extra or []),
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    procs.append((app_id, p))
    return p


def wait_for(check, timeout=10, what='condition', interval=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = check()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError('timed out waiting for ' + what)


def window_by_title(title):
    return next((w for w in windows() if w.get('caption', '').startswith(title)), None)


def shot(name):
    """Compositor screenshot of the whole screen to dist/makos/rig-launcher/<name>.png (waits for the file)."""
    dest = SHOTS / (name + '.png')
    dest.unlink(missing_ok=True)
    control('rig:shot:' + name)
    wait_for(dest.exists, 15, 'screenshot ' + name)
    time.sleep(0.2)
    return dest


def dockstate():
    f = SHOTS / 'dockstate.json'
    f.unlink(missing_ok=True)
    control('rig:dockstate')
    wait_for(f.exists, 5, 'dockstate')
    time.sleep(0.05)
    return json.loads(f.read_text())


def cleanup():
    for name, p in procs:
        if p.poll() is None:
            p.terminate()
    time.sleep(0.5)
    for name, p in procs:
        if p.poll() is None:
            p.kill()
