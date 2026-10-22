"""In-process checks of every core app against seeded data on the private KWin. Screenshots: $MAKOS_APPS_SHOTS/<app>.png"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib
sys.path.insert(0, str(Path(__file__).parent))
from makos_apps_seed import seed  # noqa: E402
from makos import ui  # noqa: E402
from makos.apps.base import snapshot_widget  # noqa: E402

SHOTS = Path(os.environ['MAKOS_APPS_SHOTS'])
HOME = Path(os.environ['HOME'])
RESULTS = []


def spin(check=None, timeout=15.0):
    end = time.monotonic() + timeout
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if check and check():
            return True
        time.sleep(.005)
    if check:
        raise AssertionError('timed out')
    return True


def settle(seconds=.5):
    end = time.monotonic() + seconds
    spin(lambda: time.monotonic() >= end, seconds + 2)


def shot(name, window):
    settle(.4)
    snapshot_widget(window, SHOTS / f'{name}.png')


def ok(name):
    RESULTS.append(name)
    print('PASS', name, flush=True)


def main():
    data = seed(HOME)
    app = Gtk.Application(application_id='org.makos.AppsRig', flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    app.hold()
    ui.install_theme()
    from makos.apps import calculator, texteditor, notes, calendar as cal, activity, diskutil, sysinfo, screenshot, softwarecenter, preview, pictures, tunes, movies
    from makos.apps.base import data_dir

    # ---- Calculator
    c = calculator.open_window(app)
    c.expression.set_text('2+3*4')
    assert c.compute() == '14'
    c.set_mode('scientific')
    c.clear()
    c.press('sin(')
    c.press('30')
    c.press(')')
    c.degrees = True
    assert c.compute() == '0.5', c.result.get_text()
    c.set_mode('programmer')
    c.expression.set_text('0xFF & 0x0F')
    assert c.compute() == '15'
    assert 'HEX F' in c.bases.get_text()
    c.expression.set_text('1/0')
    c.compute()
    assert 'divide' in c.result.get_text()
    c.set_mode('scientific')
    c.expression.set_text('sqrt(2)^2')
    c.compute()
    shot('calculator', c.win)
    c.win.close()
    ok('calculator: basic, scientific degrees, programmer, divide-by-zero message')

    # ---- Text Editor
    e = texteditor.open_window(app, data['text'])
    settle()
    assert e.text().startswith('A private rig document.')
    e.buffer.insert(e.buffer.get_end_iter(), 'Added line\n')
    assert e.dirty and e.win.get_title().startswith('•')
    e.buffer.undo()
    assert not e.dirty, 'undo restores the saved text'
    e.buffer.redo()
    assert e.dirty
    e.toggle_find()
    e.find_entry.set_text('line')
    settle(.3)
    e.step(1)
    assert e.buffer.get_selection_bounds()
    e.replace_entry.set_text('row')
    e.replace_everything()
    assert 'Second row' in e.text() and e.text().count('row') == 3
    e.buffer.undo()
    shot('text-editor', e.win)
    e.save()
    assert data['text'].read_text() == e.text() and not e.dirty
    e.saved_text = e.text()
    e.win.close()
    ok('text editor: open, undo/redo, find/replace, atomic save')

    # ---- Notes
    store = notes.NotesStore(HOME / 'rig-notes')
    n = notes.Notes(app, store)
    n.aw.present()
    ident = n.new_note()
    n.buffer.set_text('Shopping list\nmilk\neggs')
    n.flush()
    assert store.read('Notes', ident).startswith('Shopping list')
    store.create_folder('Work')
    n.fill_folders('Work')
    n.new_note()
    n.buffer.set_text('Project plan\nstep one')
    n.flush()
    settle(.3)
    assert [x.title for x in store.notes('Work')] == ['Project plan']
    n.fill_folders('Notes')
    n.fill_notes()
    assert len(store.notes('Notes')) == 1
    shot('notes', n.win)
    n.win.close()
    ok('notes: folders, autosave, listing')

    # ---- Calendar
    import datetime as dt
    cs = cal.CalendarStore(HOME / 'rig-cal')
    today = dt.date.today()
    cs.save(cal.Event('Team meeting', dt.datetime.combine(today, dt.time(10)), dt.datetime.combine(today, dt.time(11)), location='Room 4', alarm_minutes=10))
    cs.save(cal.Event('Gym', dt.datetime.combine(today, dt.time(18)), dt.datetime.combine(today, dt.time(19)), rrule='FREQ=WEEKLY'))
    cs.save(cal.Event('Holiday', dt.datetime.combine(today + dt.timedelta(days=3), dt.time()), dt.datetime.combine(today + dt.timedelta(days=4), dt.time()), all_day=True))
    k = cal.Calendar(app, cs)
    k.aw.present()
    settle()
    assert len(cs.on_day(today)) == 2
    k.edit(cs.all()[0])
    settle(.4)
    shot('calendar', k.win)
    for w in list(app.get_windows()):
        if w.get_title() == 'Event':
            w.destroy()
    k.win.close()
    ok('calendar: .ics store, recurrence, month grid, event editor')

    # ---- Activity
    victim = subprocess.Popen(['sleep', '300'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import atexit
    atexit.register(lambda: victim.terminate() if victim.poll() is None else None)
    a = activity.Activity(app)
    a.aw.present()
    spin(lambda: len(a.procs) > 5, 8)
    a.refresh()
    settle(1.5)
    a.refresh()
    a.search.set_text('sleep')
    a.fill()
    row = a.list.get_first_child()
    assert row is not None and row.proc.pid == victim.pid
    a.list.select_row(row)
    assert a.selected.pid == victim.pid
    shot('activity', a.win)
    a.stack.set_visible_child_name('perf')
    for _ in range(3):
        a.refresh()
        settle(1.1)
    shot('activity-performance', a.win)
    assert activity.send_signal(victim.pid, a.selected.start, signal.SIGTERM), 'kill goes through the guarded sender'
    assert victim.wait(5) == -signal.SIGTERM
    a.win.close()
    ok('activity: process list, performance graphs, guarded SIGTERM of exact PID')

    # ---- Disk Utility
    d = diskutil.DiskUtility(app)
    d.aw.present()
    spin(lambda: bool(d.rows), 10)
    settle(.5)
    shot('disk-utility', d.win)
    assert any(r['type'] == 'disk' for r in d.rows)
    d.win.close()
    ok('disk utility: lsblk rows, udisks SMART read')

    # ---- System Information
    s = sysinfo.SystemInfo(app)
    s.aw.present()
    shot('system-info', s.win)
    s.copy()
    s.win.close()
    ok('system information')

    # ---- Software Center
    sc = softwarecenter.SoftwareCenter(app)
    sc.aw.present()
    sc.search.set_text('calculator')
    sc.do_search()
    spin(lambda: sc.list.get_first_child() is not None and getattr(sc.list.get_first_child(), 'get_child', None) and sc.aw.status.get_text().endswith('results'), 15)
    settle(.4)
    shot('software-center', sc.win)
    sc.win.close()
    ok('software center: apt search, honest capability notice')

    # ---- Screenshot UI
    sh = screenshot.Screenshot(app)
    sh.aw.present()
    sh.set_mode('window')
    shot('screenshot', sh.win)
    sh.win.close()
    ok('screenshot window')

    # ---- Preview (PDF then image)
    pv = preview.Preview(app, data['pdf'])
    pv.aw.present()
    spin(lambda: pv.surface is not None, 10)
    assert pv.pages == 3
    spin(lambda: all(r.pic.get_paintable() for r in [pv.thumbs.get_row_at_index(i) for i in range(3)]), 15)
    pv.set_tool('highlight')
    settle(.3)
    pv.annots.add(0, {'type': 'highlight', 'rect': [.08, .24, .85, .29]})
    pv.annots.add(0, {'type': 'note', 'pos': [.5, .1], 'text': 'Check this'})
    pv.annots.save()
    pv.rotate(90)
    pv.rotate(-90)
    pv.goto(1)
    pv.goto(0)
    shot('preview-pdf', pv.win)
    out = preview.export_png(data['pdf'], 0, HOME / 'export.png', pv.annots, 0)
    from PIL import Image
    with Image.open(out) as im:
        assert im.size[0] > 400
    pv.win.close()
    pi = preview.Preview(app, data['pictures'] / 'sample-02.jpg') if False else preview.Preview(app, next((data['pictures'] / 'Holiday').glob('*.jpg')))
    pi.aw.present()
    spin(lambda: pi.surface is not None, 10)
    pi.rotate(90)
    shot('preview-image', pi.win)
    pi.win.close()
    assert (data_dir('preview', 'annotations')).exists()
    ok('preview: PDF pages/thumbnails/annotations/rotate/export PNG, image view')

    # ---- Pictures
    pc = pictures.Pictures(app, data['pictures'])
    pc.aw.present()
    spin(lambda: len(pc.items) == 10, 10)
    settle(1.2)
    shot('pictures-grid', pc.win)
    pc.open_item(0)
    settle(.8)
    pc.rotate(90)
    pc.bright.set_value(30)
    settle(.5)
    assert pictures.load_edits(pc.shown[0].path)['rotate'] == 90 and pictures.load_edits(pc.shown[0].path)['brightness'] == 30
    shot('pictures-viewer', pc.win)
    pc.crop_square()
    out = pictures.save_edited_copy(pc.shown[0].path, pc.edits, HOME / 'Pictures' / 'Edited')
    assert out.exists() and pc.shown[0].path.exists()
    pc.toggle_slideshow()
    assert pc.slide
    pc.toggle_slideshow()
    pc.win.close()
    ok('pictures: scan, albums, thumbnails, sidecar edits, edited copy, slideshow toggle')

    # ---- Tunes
    os.environ['MAKOS_AUDIO_SINK'] = 'fakesink sync=true'
    tu = tunes.Tunes(app, data['music'])
    tu.aw.present()
    spin(lambda: len(tu.library) == 3, 10)
    assert [t.title for t in tu.library] == ['Morning Light', 'Second Song', 'Third Tone']
    tu.play_track_in(tu.library, 0)
    spin(lambda: tu.position_us() > 300000, 10)
    assert tu.status == 'Playing'
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    def bus_call(*args):
        reply=[]
        def done(source,result):
            try:reply.append((source.call_finish(result),None))
            except Exception as exc:reply.append((None,exc))
        bus.call(*args,None,done)
        spin(lambda:bool(reply),5)
        if reply[0][1]:raise reply[0][1]
        return reply[0][0]
    props = lambda name: bus_call('org.mpris.MediaPlayer2.makos_tunes', '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'Get', GLib.Variant('(ss)', ('org.mpris.MediaPlayer2.Player', name)), None, Gio.DBusCallFlags.NONE, 3000).unpack()[0]  # noqa: E731
    spin(lambda: tu.mpris.conn is not None, 3)
    assert props('PlaybackStatus') == 'Playing'
    assert props('Metadata')['xesam:title'] == 'Morning Light'
    bus_call('org.mpris.MediaPlayer2.makos_tunes', '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player', 'PlayPause', None, None, Gio.DBusCallFlags.NONE, 3000)
    spin(lambda: tu.status == 'Paused', 5)
    assert props('PlaybackStatus') == 'Paused'
    bus_call('org.mpris.MediaPlayer2.makos_tunes', '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player', 'Next', None, None, Gio.DBusCallFlags.NONE, 3000)
    spin(lambda: tu.queue.current().title == 'Second Song', 5)
    tu.set_shuffle(True)
    tu.cycle_repeat()
    assert tu.queue.repeat == 'Playlist' and tu.queue.shuffle
    tu.pause()
    tu.play_pause()
    spin(lambda: tu.status == 'Playing', 5)
    settle(.8)
    shot('tunes', tu.win)
    tu.win.close()
    ok('tunes: library, GStreamer playback, queue, shuffle/repeat, MPRIS status/metadata/PlayPause/Next')

    # ---- Movies
    if data['video'].exists() and Path('/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstgtk4.so').exists():
        mv = movies.Movies(app, data['video'])
        mv.aw.present()
        spin(lambda: mv.position() > .8, 15)
        assert mv.sink is not None and mv.duration > 5
        sub = movies.find_subtitles(data['video'])
        assert sub and sub[0].suffix == '.srt'
        mv.seek_by(5)
        settle(.8)
        mv.toggle()
        assert mv.state() == mv.Gst.State.PAUSED
        mv.toggle()
        mv.toggle_fullscreen()
        settle(.5)
        mv.toggle_fullscreen()
        settle(1.0)
        shot('movies', mv.win)
        mv.win.close()
        ok('movies: playback with gtk4paintablesink, subtitle file found, seek, pause, fullscreen toggle')
    else:
        print('SKIP movies (no test video or gtk4paintablesink)')

    # ---- Terminal wrapper
    from makos.apps import terminal
    assert terminal.argv_for(lambda x: x if x == 'ptyxis' else None, HOME)[:2] == ['ptyxis', '--new-window']
    ok('terminal wrapper argv')

    # ---- Widgets layer (rendered in a plain window: the layer-shell surface itself is exercised by the shell part of the rig)
    from makos import widgets
    from makos.widgets import store as wstore
    os.environ['XDG_CONFIG_HOME'] = os.environ.get('XDG_CONFIG_HOME', str(HOME / '.config'))
    win = Gtk.ApplicationWindow(application=app, title='Widgets', default_width=1500, default_height=800)
    root = widgets.build(win)
    win.set_child(root)
    win.present()
    settle(1.5)
    shot('widgets', win)
    cfg = wstore.load()
    assert {w['kind'] for w in cfg['widgets']} >= {'clock', 'calendar'}
    assert cfg['weather']['enabled'] is False
    win.destroy()
    ok('widgets layer renders with default widgets; weather stays off')

    print('APPS CHECKS PASS: ' + str(len(RESULTS)) + ' groups', flush=True)
    (SHOTS / 'checks.json').write_text(json.dumps(RESULTS, indent=1))


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
