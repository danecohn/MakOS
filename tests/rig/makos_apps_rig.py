"""Driver for the core-app rig: shell + in-process app checks + real `makos-app` launches (exact-PID cleanup)."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
import gi
from gi.repository import Gio, GLib

ROOT = Path(os.environ['ROOT'])
T = Path(os.environ['T'])
HOME = Path(os.environ['HOME'])
SHOTS = ROOT / 'dist/makos/rig-apps'
SHOTS.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, PYTHONPATH=f'{ROOT}/src/makos:{ROOT}/src/os', MAKOS_SHARE=f'{ROOT}/src/makos', GTK_A11Y='none', MAKOS_APPS_SHOTS=str(SHOTS), MAKOS_RIG_SHOTS=str(SHOTS),
          MAKOS_LAYERSHELL_LIB=os.environ.get('AMERIKA_LAYERSHELL_LIB', '/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0'))
env.pop('LD_PRELOAD', None)
sys.path.insert(0, str(ROOT / 'tests/rig'))
from makos_apps_seed import seed  # noqa: E402
PIDS = []
failures = []


def fail(msg):
    failures.append(msg)
    print('FAIL', msg, flush=True)


def spin(seconds):
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(.02)


def wait_for(check, timeout, step=.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = check()
        if v:
            return v
        spin(step)
    return None


bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def shell(method, *args, sig=None):
    params = GLib.Variant('(s)', args) if args else None
    return bus.call_sync('org.makos.Shell', '/Control', 'org.makos.Control', method, params, None, Gio.DBusCallFlags.NONE, 8000, None).unpack()


def windows():
    state = json.loads(shell('State')[0])
    w = state['windows']
    return w.get('windows', []) if isinstance(w, dict) else w


def find_window(cls):
    return next((w for w in windows() if str(w.get('cls', '')).lower() == cls or str(w.get('desktopFile', '')).lower() == cls), None)


def desktop_shot(name):
    target = SHOTS / 'desktop.png'
    before = target.stat().st_mtime if target.exists() else 0
    shell('Action', 'shot:desktop')
    if not wait_for(lambda: target.exists() and target.stat().st_mtime > before, 20):
        fail('desktop screenshot did not complete for ' + name)
        return
    time.sleep(.3)
    shutil.copy(target, SHOTS / f'{name}.png')


def registrar_pids():
    r = bus.call_sync('com.canonical.AppMenu.Registrar', '/com/canonical/AppMenu/Registrar', 'com.canonical.AppMenu.Registrar', 'GetMenus', None, None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    return {wid & 0xffff_ffff & ~0x40000000 for wid, _s, _p in r if wid & 0x40000000}


def stop(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    wait_for(lambda: not Path(f'/proc/{pid}').exists() or Path(f'/proc/{pid}/status').read_text().find('zombie') > 0, 5)


def main():
    data = seed(HOME)
    log = open(T / 'makos-shell.log', 'w')
    shell_proc = subprocess.Popen([str(ROOT / 'src/makos/bin/makos-shell')], env=env, stdout=log, stderr=subprocess.STDOUT)
    PIDS.append(shell_proc.pid)
    ready = Path(os.environ['XDG_RUNTIME_DIR']) / 'makos/shell-ready'
    if not wait_for(lambda: ready.exists() or shell_proc.poll() is not None, 25) or shell_proc.poll() is not None:
        print(open(T / 'makos-shell.log').read())
        fail('shell did not reach ready')
        return
    print('shell ready', flush=True)
    spin(1.0)

    # 1) in-process checks of every app (own Wayland client, own GTK application)
    checks = subprocess.run([sys.executable, str(ROOT / 'tests/rig/makos_apps_checks.py')], env=env, capture_output=True, text=True, timeout=420)
    print(checks.stdout[-4000:])
    if checks.returncode != 0:
        print(checks.stderr[-4000:])
        fail('in-process app checks failed')

    # 2) real standalone launches through makos-app: window class, global menu registration, desktop screenshots
    launches = [('calculator', None), ('text-editor', str(data['text'])), ('notes', None), ('calendar', None), ('activity', None), ('disk-utility', None), ('system-info', None),
                ('software-center', None), ('preview', str(data['pdf'])), ('pictures', None), ('tunes', str(data['music'])), ('movies', str(data['video']))]
    app_env = dict(env, MAKOS_AUDIO_SINK='fakesink sync=true')
    for app_id, arg in launches:
        proc = subprocess.Popen([str(ROOT / 'src/makos/bin/makos-app'), app_id] + ([arg] if arg else []), env=app_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        PIDS.append(proc.pid)
        win = wait_for(lambda: find_window('makos-' + app_id), 20)
        if not win:
            out = ''
            if proc.poll() is not None:
                out = proc.stdout.read()
            fail(f'{app_id}: no window with class makos-{app_id} ({out[-300:]})')
            if proc.poll() is None:
                stop(proc.pid)
            continue
        if win.get('pid') != proc.pid:
            fail(f'{app_id}: window pid {win.get("pid")} != process {proc.pid}')
        registered = wait_for(lambda: proc.pid in registrar_pids(), 5)
        if not registered:
            fail(f'{app_id}: menu not registered with the shell registrar')
        spin(2.5 if app_id in ('movies', 'tunes', 'pictures', 'preview') else 1.5)
        desktop_shot(f'standalone-{app_id}')
        if app_id == 'calculator':
            # let the shell bar settle on the app so its global menu is captured
            spin(1.0)
            shell('Action', 'shot:bar')
            spin(1.0)
            if (SHOTS / 'bar.png').exists():
                shutil.copy(SHOTS / 'bar.png', SHOTS / 'global-menu-calculator.png')
        stop(proc.pid)
        proc.wait(timeout=10)
        print('standalone ok:', app_id, flush=True)

    # 3) shell launch path spawns a separate process (crash isolation) with the right class
    shell('Action', 'calculator')
    win = wait_for(lambda: find_window('makos-calculator'), 20)
    if not win or win.get('pid') == shell_proc.pid:
        fail('shell launch did not create a separate calculator process')
    elif True:
        stop(win['pid'])
        print('shell launch spawns separate process: ok', flush=True)

    # 4) Screenshot app saves through the shell's authorised capture
    out_dir = HOME / 'Pictures' / 'Screenshots'
    before = set(out_dir.glob('*.png')) if out_dir.exists() else set()
    proc = subprocess.Popen([str(ROOT / 'src/makos/bin/makos-app'), 'screenshot', '--full'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    PIDS.append(proc.pid)
    got = wait_for(lambda: (set(out_dir.glob('*.png')) - before) if out_dir.exists() else None, 25)
    if not got:
        fail('Screenshot app produced no file: ' + (proc.stdout.read()[-300:] if proc.poll() is not None else 'still running'))
    else:
        from PIL import Image
        path = sorted(got)[0]
        with Image.open(path) as im:
            if im.size != (1920, 1080) or im.getbbox() is None:
                fail(f'Screenshot has unexpected content {im.size}')
        shutil.copy(path, SHOTS / 'screenshot-result.png')
        print('screenshot app saved', path.name, flush=True)
    stop(proc.pid)

    # 5) Widgets layer through the shell's real layer-shell overlay, then toggle closed
    shell('Action', 'widgets')
    spin(2.5)
    shell('Action', 'shot:overlay')
    spin(1.0)
    if (SHOTS / 'overlay.png').exists():
        shutil.copy(SHOTS / 'overlay.png', SHOTS / 'widgets-overlay.png')
    else:
        fail('widgets overlay did not render')
    desktop_shot('widgets-desktop')
    shell('Action', 'widgets')
    spin(.8)
    print('widgets overlay opened and toggled', flush=True)

    # 6) Studio-suite launcher smoke (cosmetic wrappers around the real engines)
    rc = subprocess.run([str(ROOT / 'src/makos/bin/makos-studio-app')], env=env, capture_output=True, timeout=30).returncode
    if rc != 2:
        fail(f'makos-studio-app without arguments should exit 2, got {rc}')
    for name in ('sprite',):
        p = subprocess.Popen([str(ROOT / 'src/makos/bin/makos-studio-app'), name], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        PIDS.append(p.pid)
        spin(6)
        alive = p.poll() is None
        stop(p.pid)
        out = p.stdout.read()
        if 'Traceback' in out:
            fail(f'{name} launcher traceback: {out[-400:]}')
        print(f'studio launcher {name}: ' + ('stayed up' if alive else 'exited early: ' + out[-200:].replace("\n", " | ")), flush=True)

    # 7) shut the shell down cleanly
    shell('Action', 'quit')
    wait_for(lambda: shell_proc.poll() is not None, 10)
    log.flush()
    text = (T / 'makos-shell.log').read_text()
    shutil.copy(T / 'makos-shell.log', SHOTS / 'shell.log')
    if any(bad in text for bad in ('Traceback', 'CRITICAL', 'CSS parser error')):
        fail('shell log contains errors:\n' + text[-1500:])


try:
    main()
finally:
    for pid in PIDS:
        try:
            if Path(f'/proc/{pid}').exists():
                os.kill(pid, signal.SIGTERM)  # exact PID only, never pkill -f
        except ProcessLookupError:
            pass
if failures:
    print('APPS RIG FAILED:', *failures, sep='\n  ')
    sys.exit(1)
print('MAKOS APPS RIG PASS')
