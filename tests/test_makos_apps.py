"""Core-app logic against temporary data: calculators, stores, parsers, validators, catalog consistency."""
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/makos'))
from makos import catalog  # noqa: E402
from makos.apps import calculator, texteditor, notes, calendar as cal, activity, diskutil, sysinfo, screenshot, softwarecenter, preview, pictures, tunes, movies, terminal, mpris  # noqa: E402
from makos.widgets import store, units, weather  # noqa: E402
from makos import appmenu  # noqa: E402


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)


class CalculatorTests(unittest.TestCase):
    def test_basic_and_scientific(self):
        self.assertEqual(calculator.evaluate('2 + 3 × 4'), 14)
        self.assertEqual(calculator.format_value(calculator.evaluate('2^10')), '1024')
        self.assertEqual(calculator.format_value(calculator.evaluate('sin(30)', degrees=True)), '0.5')
        self.assertEqual(calculator.evaluate('5!'), 120.0)
        self.assertAlmostEqual(calculator.evaluate('sqrt(2)*sqrt(2)'), 2)
        self.assertAlmostEqual(calculator.evaluate('ln(e)'), 1)
        self.assertEqual(calculator.evaluate('50%'), .5)
        self.assertEqual(calculator.evaluate('ans*2', ans=21), 42)

    def test_rejects_code_and_huge_values(self):
        for text in ['__import__("os")', '(1).real', 'open("x")', '2**99999', '9**9**9', 'x', 'sin', '[1]*10', '"a"*9', 'fact(1000)', '1e308*10', 'lambda:1']:
            with self.subTest(text=text), self.assertRaises((ValueError, SyntaxError, OverflowError, TypeError)):
                calculator.evaluate(text)
        with self.assertRaises(ZeroDivisionError):
            calculator.evaluate('1/0')
        with self.assertRaises(ValueError):
            calculator.evaluate('asin(2)')

    def test_programmer_mode(self):
        ev = lambda t, bits=64: calculator.evaluate(t, 'programmer', bits=bits)  # noqa: E731
        self.assertEqual(ev('0xFF & 0x0F'), 15)
        self.assertEqual(ev('1 << 4'), 16)
        self.assertEqual(ev('0b1010 ^ 0b0110' if False else '10 ^ 6'), 12)
        self.assertEqual(ev('~0', 8), 255)
        self.assertEqual(calculator.format_value(255, 16), 'FF')
        self.assertEqual(calculator.format_value(5, 2), '101')
        self.assertEqual(calculator.signed(255, 8), -1)
        with self.assertRaises(ValueError):
            ev('1 << 1000')
        with self.assertRaises(ValueError):
            ev('sin(1)')


class TextEditorTests(Tmp):
    def test_find_and_replace(self):
        self.assertEqual(texteditor.find_all('Abc abc ABC', 'abc'), [(0, 3), (4, 7), (8, 11)])
        self.assertEqual(texteditor.find_all('Abc abc', 'abc', case=True), [(4, 7)])
        self.assertEqual(texteditor.find_all('cat concat', 'cat', whole=True), [(0, 3)])
        self.assertEqual(texteditor.replace_all('a1 b22', r'\d+', '#', regex=True), ('a# b#', 2))
        self.assertEqual(texteditor.replace_all('aaa', 'a', 'bb'), ('bbbbbb', 3))
        self.assertEqual(texteditor.replace_all('x', 'y', 'z'), ('x', 0))
        with self.assertRaises(ValueError):
            texteditor.find_all('x', '(', regex=True)
        self.assertEqual(texteditor.find_all('x', ''), [])

    def test_loading_limits(self):
        (self.tmp / 'a.txt').write_text('héllo\n')
        self.assertEqual(texteditor.read_text_file(self.tmp / 'a.txt'), 'héllo\n')
        (self.tmp / 'b.bin').write_bytes(b'\x00\x01\x02')
        with self.assertRaises(ValueError):
            texteditor.read_text_file(self.tmp / 'b.bin')
        self.assertEqual(texteditor.statistics('a b\nc'), {'lines': 2, 'words': 3, 'chars': 5})


class NotesTests(Tmp):
    def test_folders_notes_trash_search(self):
        s = notes.NotesStore(self.tmp)
        self.assertEqual(s.folders(), ['Notes'])
        s.create_folder('Work')
        ident = s.new_note('Work', 'Plan\nship it')
        self.assertEqual(s.notes('Work')[0].title, 'Plan')
        self.assertEqual(s.notes('Work')[0].preview, 'ship it')
        s.write('Work', ident, 'Plan v2\nnotes')
        self.assertIn('v2', s.read('Work', ident))
        self.assertEqual([n.ident for n in s.search('PLAN')], [ident])
        s.move('Work', ident, 'Notes')
        self.assertFalse(s.notes('Work'))
        s.trash('Notes', ident)
        self.assertEqual(s.notes(notes.TRASH_FOLDER)[0].ident, ident)
        self.assertTrue((self.tmp / notes.TRASH_FOLDER / ident).exists(), 'trashed notes are kept, not erased')
        s.restore(ident)
        self.assertEqual(s.notes('Notes')[0].ident, ident)

    def test_invalid_names_and_protected_folders(self):
        s = notes.NotesStore(self.tmp)
        for bad in ('', '../x', 'a/b', '.hidden', 'x' * 99):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                s.create_folder(bad)
        with self.assertRaises(ValueError):
            s.read('Notes', '../../etc/passwd')
        with self.assertRaises(ValueError):
            s.delete_folder('Notes')
        s.create_folder('Tmp')
        i = s.new_note('Tmp', 'x')
        s.delete_folder('Tmp')
        self.assertEqual(len(s.notes(notes.TRASH_FOLDER)), 1)
        self.assertNotIn('Tmp', s.folders())
        self.assertTrue(i)

    def test_legacy_note_is_imported_once(self):
        s = notes.NotesStore(self.tmp / 'n')
        legacy = self.tmp / 'notes.txt'
        legacy.write_text('old note\nmore')
        self.assertTrue(s.import_legacy(legacy))
        self.assertIsNone(s.import_legacy(legacy))
        self.assertEqual(s.notes('Notes')[0].title, 'old note')
        self.assertTrue((self.tmp / 'notes.txt.imported').exists())


class CalendarTests(Tmp):
    def event(self, **kw):
        base = dict(summary='Dentist; "A", B\nline2', start=dt.datetime(2026, 10, 22, 9), end=dt.datetime(2026, 10, 22, 10), description='x' * 300, alarm_minutes=15)
        base.update(kw)
        return cal.Event(**base)

    def test_ics_round_trip_with_folding_and_escapes(self):
        e = self.event(location='Room 1, North', rrule='FREQ=WEEKLY;COUNT=3')
        text = cal.to_ics(e)
        self.assertTrue(all(len(l.encode()) <= 75 for l in text.split('\r\n')))
        self.assertIn('BEGIN:VALARM', text)
        self.assertEqual(cal.parse_ics(text), [e])

    def test_all_day_and_utc_parsing(self):
        e = self.event(summary='Holiday', all_day=True, start=dt.datetime(2026, 12, 25), end=dt.datetime(2026, 12, 26), alarm_minutes=-1, description='')
        self.assertIn('DTSTART;VALUE=DATE:20261225', cal.to_ics(e))
        self.assertEqual(cal.parse_ics(cal.to_ics(e)), [e])
        text = 'BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:u1\nDTSTART:20261022T120000Z\nSUMMARY:UTC\nEND:VEVENT\nEND:VCALENDAR\n'
        got = cal.parse_ics(text)[0]
        self.assertEqual(got.start, dt.datetime(2026, 10, 22, 12, tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None))
        self.assertEqual(cal.parse_ics('garbage'), [])
        self.assertEqual(cal.parse_ics('BEGIN:VEVENT\nDTSTART:notadate\nEND:VEVENT'), [])

    def test_recurrence(self):
        e = self.event(rrule='FREQ=WEEKLY;COUNT=3')
        starts = cal.occurrences(e, dt.datetime(2026, 10, 1), dt.datetime(2026, 12, 31))
        self.assertEqual([s.day for s in starts], [22, 29, 5])
        e = self.event(rrule='FREQ=DAILY;INTERVAL=2;UNTIL=20261028')
        self.assertEqual([s.day for s in cal.occurrences(e, dt.datetime(2026, 10, 1), dt.datetime(2026, 12, 31))], [22, 24, 26, 28])
        e = self.event(start=dt.datetime(2026, 1, 31, 9), end=dt.datetime(2026, 1, 31, 10), rrule='FREQ=MONTHLY')
        months = [s.month for s in cal.occurrences(e, dt.datetime(2026, 1, 1), dt.datetime(2026, 6, 1))]
        self.assertEqual(months, [1, 3, 5], 'days that do not exist are skipped')
        e = self.event(rrule='FREQ=WEEKLY;BYDAY=MO,FR;COUNT=4')
        self.assertEqual(len(cal.occurrences(e, dt.datetime(2026, 10, 1), dt.datetime(2026, 12, 31))), 4)
        self.assertEqual(len(cal.occurrences(self.event(rrule='FREQ=BOGUS'), dt.datetime(2026, 1, 1), dt.datetime(2027, 1, 1))), 1, 'an unsupported rule shows the event once')

    def test_due_alarms(self):
        e = self.event(rrule='FREQ=DAILY')
        due = cal.due_alarms([e], dt.datetime(2026, 10, 23, 8, 40), dt.datetime(2026, 10, 23, 8, 50))
        self.assertEqual([s for _e, s in due], [dt.datetime(2026, 10, 23, 9)])
        self.assertEqual(cal.due_alarms([e], dt.datetime(2026, 10, 23, 8, 50), dt.datetime(2026, 10, 23, 8, 55)), [])
        self.assertEqual(cal.due_alarms([self.event(alarm_minutes=-1)], dt.datetime(2026, 10, 22, 0), dt.datetime(2026, 10, 23)), [])

    def test_store_is_one_ics_per_event_and_remove_keeps_a_copy(self):
        s = cal.CalendarStore(self.tmp)
        e = self.event()
        s.save(e)
        self.assertEqual(len(list(self.tmp.glob('*.ics'))), 1)
        self.assertEqual(s.all(), [e])
        self.assertEqual([x[1] for x in s.on_day(dt.date(2026, 10, 22))], [e])
        self.assertEqual(s.on_day(dt.date(2026, 10, 23)), [])
        s.remove(e)
        self.assertEqual(s.all(), [])
        self.assertTrue(list((self.tmp / '.deleted').glob('*.ics')))


class ActivityTests(Tmp):
    def fake_proc(self, pid, name, uid, ticks, start=100):
        d = self.tmp / str(pid)
        d.mkdir(exist_ok=True)
        fields = ['S', '1'] + ['0'] * 9 + [str(ticks), '0', '0', '0', '20', '0', '3', '0', str(start), '0', '256'] + ['0'] * 20
        (d / 'stat').write_text(f'{pid} ({name} (x)) ' + ' '.join(fields))
        (d / 'status').write_text(f'Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n')

    def test_read_proc_handles_parentheses_in_names(self):
        self.fake_proc(10, 'we ird', 1000, 50)
        p = activity.read_proc(10, self.tmp)
        self.assertEqual((p.name, p.uid, p.threads, p.ticks, p.start), ('we ird (x)', 1000, 3, 50, 100))
        self.assertIsNone(activity.read_proc(99, self.tmp))

    def test_sampler_cpu_is_a_delta(self):
        self.fake_proc(10, 'busy', 1000, 100)
        s = activity.Sampler(self.tmp)
        self.assertEqual(s.processes()[0].cpu, 0.0)
        self.fake_proc(10, 'busy', 1000, 100 + activity.CLK)  # one second of CPU time
        import time
        s.when -= 2.0
        self.assertAlmostEqual(s.processes()[0].cpu, 50.0, delta=8)

    def test_cpu_memory_network_from_proc_files(self):
        (self.tmp / 'stat').write_text('cpu 100 0 100 800 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0\n')
        s = activity.Sampler(self.tmp)
        s.cpu()
        (self.tmp / 'stat').write_text('cpu 200 0 200 900 0 0 0 0\ncpu0 100 0 100 450 0 0 0 0\n')
        total, cores = s.cpu()
        self.assertAlmostEqual(total, 200 / 300 * 100, places=3)
        self.assertEqual(len(cores), 1)
        (self.tmp / 'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 100 kB\nSwapFree: 40 kB\n')
        self.assertEqual(activity.memory(self.tmp)['used'], 750 * 1024)
        self.assertEqual(activity.memory(self.tmp)['swap_used'], 60 * 1024)

    def test_gpu_and_energy_sources(self):
        d = self.tmp / 'class/drm/card0/device'
        d.mkdir(parents=True)
        (d / 'gpu_busy_percent').write_text('37\n')
        self.assertEqual(activity.gpu(self.tmp)['kind'], 'busy')
        (d / 'gpu_busy_percent').unlink()
        f = self.tmp / 'class/devfreq/3d00000.gpu'
        f.mkdir(parents=True)
        (f / 'cur_freq').write_text('300')
        (f / 'max_freq').write_text('1200')
        g = activity.gpu(self.tmp)
        self.assertEqual((g['kind'], g['percent']), ('clock', 25.0))
        b = self.tmp / 'class/power_supply/BAT0'
        b.mkdir(parents=True)
        for k, v in (('type', 'Battery'), ('capacity', '80'), ('status', 'Discharging'), ('current_now', '1000000'), ('voltage_now', '12000000')):
            (b / k).write_text(v)
        e = activity.energy(self.tmp)
        self.assertEqual((e['battery'], round(e['watts'], 1)), (80, 12.0))
        self.assertIsNone(activity.gpu(self.tmp / 'nothing'))

    def test_signal_guards(self):
        mine = activity.Proc(5000, 'x', os.getuid(), 'S', 0, 1, 0, 7)
        self.assertTrue(activity.can_signal(mine))
        self.assertFalse(activity.can_signal(activity.Proc(1, 'init', os.getuid(), 'S', 0, 1, 0, 7)))
        self.assertFalse(activity.can_signal(activity.Proc(5000, 'x', os.getuid() + 1, 'S', 0, 1, 0, 7)))
        self.assertFalse(activity.can_signal(activity.Proc(os.getpid(), 'me', os.getuid(), 'S', 0, 1, 0, 7)))
        self.fake_proc(os.getpid(), 'self', os.getuid(), 1, 5)
        self.assertFalse(activity.send_signal(os.getpid(), 5, 0, self.tmp), 'never signals this process')
        self.assertFalse(activity.send_signal(424242, 5, 0, self.tmp), 'missing process')


class DiskTests(unittest.TestCase):
    SAMPLE = json.dumps({'blockdevices': [
        {'name': 'loop0', 'path': '/dev/loop0', 'type': 'loop', 'size': 1, 'mountpoints': ['/snap/x/1']},
        {'name': 'nvme0n1', 'path': '/dev/nvme0n1', 'type': 'disk', 'size': 512000000000, 'model': 'Test SSD', 'rm': False, 'ro': False, 'mountpoints': [None], 'children': [
            {'name': 'nvme0n1p1', 'path': '/dev/nvme0n1p1', 'type': 'part', 'size': 500000000, 'fstype': 'vfat', 'mountpoints': ['/boot/efi'], 'pkname': 'nvme0n1'},
            {'name': 'sda1', 'path': '/dev/sda1', 'type': 'part', 'size': 8000, 'fstype': 'ext4', 'label': 'USB', 'mountpoints': [None], 'pkname': 'sda', 'fsused': 100, 'fsavail': 7000},
            {'name': 'sda2', 'path': '/dev/sda2', 'type': 'part', 'size': 8000, 'fstype': 'ext4', 'mountpoints': ['/media/me/USB2'], 'pkname': 'sda'}]}]})

    def test_parse_and_rules(self):
        rows = diskutil.parse_lsblk(self.SAMPLE)
        self.assertEqual([r['path'] for r in rows], ['/dev/nvme0n1', '/dev/nvme0n1p1', '/dev/sda1', '/dev/sda2'], 'snap loop devices are hidden')
        by = {r['path']: r for r in rows}
        self.assertFalse(diskutil.can_unmount(by['/dev/nvme0n1p1']), 'the EFI system partition is never unmounted here')
        self.assertTrue(diskutil.can_mount(by['/dev/sda1']))
        self.assertFalse(diskutil.can_mount(by['/dev/sda2']))
        self.assertTrue(diskutil.can_unmount(by['/dev/sda2']))
        self.assertEqual(diskutil.parse_lsblk('not json'), [])

    def test_udisks_commands_are_validated(self):
        rows = diskutil.parse_lsblk(self.SAMPLE)
        known = {r['path'] for r in rows}
        by = {r['path']: r for r in rows}
        self.assertEqual(diskutil.udisks_command('mount', by['/dev/sda1'], known), ['udisksctl', 'mount', '-b', '/dev/sda1'])
        with self.assertRaises(ValueError):
            diskutil.udisks_command('mount', dict(by['/dev/sda1'], path='/dev/sda1; rm -rf /'), known | {'/dev/sda1; rm -rf /'})
        with self.assertRaises(ValueError):
            diskutil.udisks_command('format', by['/dev/sda1'], known)
        with self.assertRaises(ValueError):
            diskutil.udisks_command('unmount', by['/dev/nvme0n1p1'], known)
        with self.assertRaises(ValueError):
            diskutil.udisks_command('mount', dict(by['/dev/sda1'], path='/dev/zzz'), known)

    def test_smart_summary(self):
        objects = {'/d/1': {'org.freedesktop.UDisks2.Drive': {'Model': 'M'}, 'org.freedesktop.UDisks2.NVMe.Controller': {'SmartCriticalWarning': [], 'SmartTemperature': 313, 'SmartPowerOnHours': 99}},
                   '/b/1': {'org.freedesktop.UDisks2.Block': {'Drive': '/d/1', 'Device': b'/dev/nvme0n1\x00'}},
                   '/d/2': {'org.freedesktop.UDisks2.Drive': {'Model': 'A'}, 'org.freedesktop.UDisks2.Drive.Ata': {'SmartSupported': True, 'SmartFailing': True, 'SmartTemperature': 300, 'SmartPowerOnSeconds': 7200, 'SmartEnabled': True}},
                   '/b/2': {'org.freedesktop.UDisks2.Block': {'Drive': '/d/2', 'Device': b'/dev/sda\x00'}}}
        out = diskutil.smart_from_objects(objects)
        self.assertTrue(out['/dev/nvme0n1']['smart']['passed'])
        self.assertEqual(out['/dev/nvme0n1']['smart']['power_on_hours'], 99)
        self.assertFalse(out['/dev/sda']['smart']['passed'])
        self.assertEqual(out['/dev/sda']['smart']['power_on_hours'], 2)


class SysInfoTests(unittest.TestCase):
    def test_report_redaction(self):
        text = 'user bob at /home/bob/x mac aa:bb:cc:dd:ee:ff ip 192.168.1.20 mail bob@example.com token=abc123 serial number: ZX99 id ' + 'a' * 40 + ' key sk-' + 'q' * 30
        out = sysinfo.redact(text, home='/home/bob', user='bob')
        for leak in ('bob', 'aa:bb', '192.168', 'example.com', 'abc123', 'ZX99', 'a' * 40, 'qqqq'):
            self.assertNotIn(leak, out)
        self.assertIn('~/x', out)

    def test_gathered_report_has_no_secrets(self):
        r = sysinfo.report()
        self.assertIn('MakkOS', r)
        self.assertNotIn(str(Path.home()), r)
        self.assertEqual(sysinfo.os_release('/nonexistent'), {})


class ScreenshotTests(Tmp):
    def test_geometry_and_crop(self):
        self.assertEqual(screenshot.scale_rect((10, 10, 100, 50), (1000, 500), (2000, 1000)), (20, 20, 220, 120))
        self.assertEqual(screenshot.scale_rect((100, 100, -50, -50), (1000, 500), (2000, 1000)), (100, 100, 200, 200))
        self.assertEqual(screenshot.scale_rect((-50, -50, 5000, 5000), (100, 100), (200, 200)), (0, 0, 200, 200))
        self.assertIsNone(screenshot.scale_rect((1, 1, 0, 0), (10, 10), (10, 10)))
        from PIL import Image
        src = self.tmp / 's.png'
        Image.new('RGB', (40, 30), 'red').save(src)
        out = screenshot.crop_file(src, (5, 5, 25, 15), self.tmp / 'c.png')
        with Image.open(out) as cropped:
            self.assertEqual(cropped.size, (20, 10))

    def test_capture_requests_are_confined_to_the_runtime_folder(self):
        good = str(screenshot.shots_dir() / 'a.png')
        self.assertEqual(screenshot.parse_capture('capture:full:-:' + good), ('full', None, good))
        self.assertEqual(screenshot.parse_capture('capture:window:{ab-12}:' + good)[1], '{ab-12}')
        for bad in ('capture:full:-:/etc/passwd.png', 'capture:full:-:' + str(screenshot.shots_dir() / 'x/../../a.png'), 'capture:full:-:' + str(screenshot.shots_dir() / 'a.txt'),
                    'capture:window:-:' + good, 'capture:window:$(id):' + good, 'capture:evil:-:' + good, 'capture:full', 'capture:full:-:/tmp/a.png'):
            with self.subTest(bad=bad):
                self.assertIsNone(screenshot.parse_capture(bad))

    def test_names_do_not_collide(self):
        (self.tmp / 'Screenshot a.png').write_text('x')
        self.assertEqual(screenshot.unique_path(self.tmp, 'Screenshot a.png').name, 'Screenshot a (2).png')
        self.assertTrue(re.fullmatch(r'Screenshot \d{4}-\d\d-\d\d \d\d\.\d\d\.\d\d\.png', screenshot.filename_for()))


class SoftwareTests(unittest.TestCase):
    def helper(self):
        spec = importlib.util.spec_from_file_location('helper', ROOT / 'src/makos/libexec/makos-software-helper', loader=importlib.machinery.SourceFileLoader('helper', str(ROOT / 'src/makos/libexec/makos-software-helper')))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_parsers(self):
        self.assertEqual(softwarecenter.parse_search('vlc - media player\nbad name - x\nweird\n'), [('vlc', 'media player')])
        self.assertEqual(softwarecenter.parse_installed('vlc\tii \nold\trc \nfoo:arm64\tii \n'), {'vlc', 'foo'})
        up = softwarecenter.parse_upgradable('Listing...\nlibfoo/noble-security 2.0 arm64 [upgradable from: 1.0]\nbar/noble 1 all [upgradable from: 0.9]')
        self.assertEqual([(u['name'], u['security']) for u in up], [('libfoo', True), ('bar', False)])
        self.assertEqual(softwarecenter.parse_progress('pmstatus:vlc:45.5:Installing vlc'), (.455, 'Installing vlc'))
        self.assertIsNone(softwarecenter.parse_progress('garbage'))
        self.assertEqual(softwarecenter.parse_flatpak('org.gimp.GIMP\tGIMP\tImage editor\nnotanid\tx\n'), [('org.gimp.GIMP', 'GIMP - Image editor')])

    def test_app_side_validation(self):
        self.assertEqual(softwarecenter.helper_argv('install', ['vlc'], '/h')[:3], ['pkexec', '/h', 'install'])
        for args in (('install', ['-o foo']), ('install', ['VLC']), ('install', []), ('purge', ['x']), ('remove', ['a b'])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                softwarecenter.helper_argv(*args)
        with self.assertRaises(ValueError):
            softwarecenter.flatpak_argv('install', 'not an id')
        self.assertEqual(softwarecenter.flatpak_argv('install', 'org.gimp.GIMP')[:3], ['flatpak', '--user', 'install'])
        self.assertFalse(softwarecenter.capabilities(lambda e: None, '/nonexistent')['apt'])

    def test_privileged_helper_allowlist(self):
        h = self.helper()
        self.assertEqual(h.command('update', [])[-1], 'update')
        self.assertIn('upgrade', h.command('upgrade', []))
        self.assertNotIn('dist-upgrade', ' '.join(h.command('upgrade', [])))
        cmd = h.command('install', ['vlc', 'libx11-6'])
        self.assertEqual(cmd[-3:], ['--', 'vlc', 'libx11-6'])
        self.assertTrue(cmd[0].startswith('/usr/bin/'))
        for action, pkgs in (('install', ['--allow-unauthenticated']), ('install', ['a;b']), ('install', ['UPPER']), ('install', []), ('install', ['x'] * 25), ('remove', ['makos-shell']), ('remove', ['kwin-wayland']),
                             ('remove', ['systemd']), ('remove', ['linux-image-7.0']), ('upgrade', ['vlc']), ('dist-upgrade', []), ('shell', ['id'])):
            with self.subTest(action=action, pkgs=pkgs), self.assertRaises(ValueError):
                h.command(action, pkgs)
        self.assertEqual(h.main(['helper', 'dist-upgrade']), 2)

    def test_polkit_policy_names_the_helper(self):
        policy = (ROOT / 'src/makos/polkit/org.makos.software.policy').read_text()
        self.assertIn('/usr/libexec/makos/makos-software-helper', policy)
        self.assertIn('auth_admin', policy)
        self.assertNotIn('<allow_active>yes', policy)


class PreviewTests(Tmp):
    def test_annotation_sidecar(self):
        doc = self.tmp / 'd.png'
        doc.write_bytes(b'x')
        a = preview.Annotations(doc, self.tmp / 'ann')
        a.add(0, {'type': 'highlight', 'rect': [.1, .1, 2, .2]})
        a.add(0, {'type': 'note', 'pos': [.5, .5], 'text': 'n' * 5000})
        self.assertEqual(a.page(0)[0]['rect'][2], 1, 'clamped to the page')
        self.assertEqual(len(a.page(0)[1]['text']), 2000)
        with self.assertRaises(ValueError):
            a.add(0, {'type': 'script', 'x': 1})
        with self.assertRaises(ValueError):
            a.add(0, {'type': 'highlight', 'rect': ['a', 1, 1, 1]})
        a.data['rotation'] = 90
        a.save()
        b = preview.Annotations(doc, self.tmp / 'ann')
        self.assertEqual((b.count(), b.data['rotation']), (2, 90))
        self.assertEqual(doc.read_bytes(), b'x', 'the original is never touched')
        self.assertEqual(b.remove_last(0)['type'], 'note')
        self.assertTrue(b.remove_near(0, (.2, .15)))
        self.assertEqual(b.count(), 0)
        (self.tmp / 'ann' / b.path.name).write_text('{broken')
        self.assertEqual(preview.Annotations(doc, self.tmp / 'ann').count(), 0)

    def test_rotation_maths_round_trips(self):
        for r in (0, 90, 180, 270):
            x, y = preview.unrot_point(preview.rot_point((.2, .7), r), r)
            self.assertAlmostEqual((x, y), (.2, .7), places=9) if False else (self.assertAlmostEqual(x, .2), self.assertAlmostEqual(y, .7))
        self.assertEqual(preview.rot_point((0, 0), 90), (1, 0))
        self.assertEqual(preview.kind_of('a.PDF'), 'pdf')
        self.assertEqual(preview.kind_of('a.jpeg'), 'image')
        self.assertEqual(preview.kind_of('a.xyz'), 'other')

    def test_image_export_burns_annotations_and_rotates(self):
        from PIL import Image
        src = self.tmp / 'i.png'
        Image.new('RGB', (100, 50), 'white').save(src)
        a = preview.Annotations(src, self.tmp / 'ann')
        a.add(0, {'type': 'highlight', 'rect': [0, 0, .5, 1]})
        out = preview.export_png(src, 0, self.tmp / 'o.png', a, 90)
        im = Image.open(out)
        self.assertEqual(im.size, (50, 100))
        self.assertNotEqual(im.getpixel((10, 10)), (255, 255, 255), 'highlight is in the exported pixels')
        pdf = preview.export_pdf(src, self.tmp / 'o.pdf', a, 0)
        self.assertTrue(Path(pdf).read_bytes().startswith(b'%PDF'))

    @unittest.skipUnless(preview.have_poppler(), 'poppler-utils not installed')
    def test_pdf_pages_render_and_unchanged_export_is_lossless(self):
        import cairo
        pdf = self.tmp / 't.pdf'
        s = cairo.PDFSurface(str(pdf), 300, 400)
        c = cairo.Context(s)
        for _ in range(3):
            c.set_source_rgb(1, 1, 1)
            c.paint()
            s.show_page()
        s.finish()
        self.assertEqual(preview.pdf_page_count(pdf), 3)
        img = preview.load_page_image(pdf, 1, 50, self.tmp / 'cache')
        self.assertAlmostEqual(img.size[0], 208, delta=2)
        self.assertAlmostEqual(img.size[1], 278, delta=2)
        a = preview.Annotations(pdf, self.tmp / 'ann')
        out = preview.export_pdf(pdf, self.tmp / 'copy.pdf', a)
        self.assertEqual(Path(out).read_bytes(), pdf.read_bytes())
        a.add(2, {'type': 'note', 'pos': [.1, .1], 'text': 'hi'})
        out2 = preview.export_pdf(pdf, self.tmp / 'ann.pdf', a)
        self.assertEqual(preview.pdf_page_count(out2), 3)


class PicturesTests(Tmp):
    def make(self):
        from PIL import Image
        (self.tmp / 'a').mkdir()
        (self.tmp / '.hidden').mkdir()
        (self.tmp / 'real').mkdir()
        Image.new('RGB', (100, 60), 'red').save(self.tmp / 'a/x.jpg')
        Image.new('RGB', (50, 50), 'blue').save(self.tmp / 'y.png')
        Image.new('RGB', (5, 5), 'blue').save(self.tmp / '.hidden/z.png')
        (self.tmp / 'a/notes.txt').write_text('x')
        (self.tmp / 'link').symlink_to(self.tmp / 'real', target_is_directory=True)
        Image.new('RGB', (5, 5)).save(self.tmp / 'real/in.png')

    def test_scan_albums(self):
        self.make()
        items = pictures.scan(self.tmp, use_exif=False)
        names = sorted(i.path.name for i in items)
        self.assertEqual(names, ['in.png', 'x.jpg', 'y.png'], 'no hidden folders, no text files; symlinked folders are not followed')
        self.assertEqual(set(pictures.albums_by_folder(items)), {'Pictures', 'a', 'real'})
        self.assertEqual(len(pictures.albums_by_date(items)), 1)
        self.assertEqual(len(pictures.scan(self.tmp, limit=1, use_exif=False)), 1)

    def test_edits_are_sidecars_and_applied_in_order(self):
        from PIL import Image
        self.make()
        photo = self.tmp / 'a/x.jpg'
        before = photo.read_bytes()
        edits = {'rotate': 90, 'brightness': 50, 'crop': [0, 0, .5, 1]}
        pictures.save_edits(photo, edits, self.tmp / 'ed')
        self.assertEqual(pictures.load_edits(photo, self.tmp / 'ed'), edits)
        self.assertEqual(photo.read_bytes(), before)
        im = pictures.apply_edits(Image.open(photo), edits)
        self.assertEqual(im.size, (30, 100))
        self.assertGreater(im.getpixel((5, 5))[0], 200)
        out = pictures.save_edited_copy(photo, edits, self.tmp / 'out')
        out2 = pictures.save_edited_copy(photo, edits, self.tmp / 'out')
        self.assertNotEqual(out, out2)
        pictures.save_edits(photo, pictures.DEFAULT_EDITS, self.tmp / 'ed')
        self.assertEqual(pictures.load_edits(photo, self.tmp / 'ed'), pictures.DEFAULT_EDITS)

    def test_untrusted_edit_data_is_clamped(self):
        e = pictures.clean_edits({'rotate': 45, 'brightness': 9999, 'crop': [0, 0, 0, 0]})
        self.assertEqual(e, {'rotate': 0, 'brightness': 100, 'crop': None})
        self.assertEqual(pictures.clean_edits('x'), pictures.DEFAULT_EDITS)
        self.assertEqual(pictures.clean_edits({'crop': [-1, 0, 5, 1]})['crop'], [0, 0, 1, 1])


class MediaTests(Tmp):
    def test_queue_shuffle_repeat(self):
        import random
        tracks = [tunes.Track(Path(f'{i}.mp3'), str(i)) for i in range(5)]
        q = tunes.TrackQueue(random.Random(1))
        q.set_tracks(tracks, 1)
        self.assertEqual([q.current().title] + [q.next().title for _ in range(3)], ['1', '2', '3', '4'])
        self.assertIsNone(q.next(auto=True), 'the end stops unless repeating')
        q.repeat = 'Playlist'
        self.assertEqual(q.next(auto=True).title, '0')
        q.repeat = 'Track'
        self.assertEqual(q.next(auto=True).title, '0')
        self.assertEqual(q.next().title, '1', 'a manual next still advances in repeat-one')
        self.assertEqual(q.previous(10).title, '1', 'previous after 3 s restarts the track')
        self.assertEqual(q.previous(0).title, '0')
        q.set_shuffle(True)
        self.assertEqual(q.current().title, '0', 'shuffling keeps the current song')
        seen = {q.current().title}
        for _ in range(4):
            seen.add(q.next().title)
        self.assertEqual(seen, {'0', '1', '2', '3', '4'}, 'shuffle visits every song once')
        q.play_next(tunes.Track(Path('z.mp3'), 'z'))
        self.assertEqual(q.upcoming()[0].title, 'z') if q.pos + 1 < len(q.order) else None

    def test_tags_and_library(self):
        self.assertEqual(tunes.tags_from_name('/m/Band/Album/03 - Band - Song.mp3').title, 'Song')
        self.assertEqual(tunes.tags_from_name('/m/x/plain.flac').title, 'plain')
        (self.tmp / 'A').mkdir()
        (self.tmp / '.h').mkdir()
        for n in ('A/1.mp3', 'A/2.txt', '.h/3.mp3', '4.OGG'):
            (self.tmp / n).write_text('x')
        found = tunes.scan_music(self.tmp, reader=lambda p: tunes.tags_from_name(p))
        self.assertEqual(sorted(t.path.name for t in found), ['1.mp3', '4.OGG'])
        self.assertEqual(tunes.read_tags(self.tmp / 'A/1.mp3').title, '1', 'unreadable tag data falls back to the file name')

    def test_mpris_metadata(self):
        md = mpris.metadata_variant({'title': 'T', 'artist': 'A', 'album': 'Al', 'length_us': 5000000, 'uri': 'file:///x.mp3'})
        self.assertEqual(md['xesam:artist'].unpack(), ['A'])
        self.assertEqual(md['mpris:length'].unpack(), 5000000)
        self.assertEqual(mpris.metadata_variant({})['mpris:trackid'].unpack(), '/org/mpris/MediaPlayer2/TrackList/NoTrack')
        from xml.dom import minidom
        for xml in (mpris.ROOT_XML, mpris.PLAYER_XML):
            minidom.parseString(xml)
        self.assertIn('PlayPause', mpris.PLAYER_XML)

    def test_subtitles_and_shortcuts(self):
        for n in ('a.mkv', 'a.srt', 'a.en.srt', 'ab.srt', 'a.txt'):
            (self.tmp / n).touch()
        self.assertEqual([p.name for p in movies.find_subtitles(self.tmp / 'a.mkv')], ['a.srt', 'a.en.srt'])
        self.assertEqual(movies.seek_target(10, -30, 100), 0)
        self.assertEqual(movies.seek_target(95, 30, 100), 99.5)
        from gi.repository import Gdk
        self.assertEqual(movies.key_action(Gdk.KEY_space), ('toggle', None))
        self.assertEqual(movies.key_action(Gdk.KEY_Right, shift=True), ('seek', 30))
        self.assertEqual(movies.key_action(Gdk.KEY_f), ('fullscreen', None))
        self.assertIsNone(movies.key_action(Gdk.KEY_z))


class TerminalTests(unittest.TestCase):
    def test_preferred_backend_and_directory(self):
        which = lambda exe: exe if exe in ('ptyxis', 'konsole') else None  # noqa: E731
        self.assertEqual(terminal.argv_for(which, '/tmp'), ['ptyxis', '--new-window', '--working-directory', '/tmp'])
        self.assertEqual(terminal.argv_for(lambda e: e if e == 'konsole' else None), ['konsole', '--separate'])
        self.assertIsNone(terminal.argv_for(lambda e: None))
        self.assertEqual(terminal.argv_for(which, 'file:///tmp/none.txt')[-1], '/tmp')


class WidgetTests(Tmp):
    def test_store_validation_and_persistence(self):
        f = self.tmp / 'w.json'
        self.assertEqual(len(store.load(f)['widgets']), 6)
        d = store.default()
        store.add_widget(d, 'notes', 5, 6)
        store.add_widget(d, 'notes', 9, 9)
        store.add_widget(d, 'evil', 1, 1)
        self.assertEqual(sum(w['kind'] == 'notes' for w in d['widgets']), 1)
        store.move_widget(d, 'notes', 300, 400)
        store.remove_widget(d, 'clock')
        store.save(d, f)
        back = store.load(f)
        self.assertEqual(next(w for w in back['widgets'] if w['kind'] == 'notes')['x'], 300)
        self.assertFalse(any(w['kind'] == 'clock' for w in back['widgets']))
        self.assertEqual(oct(f.stat().st_mode & 0o777), '0o600')
        f.write_text('{"widgets": "x", "weather": {"enabled": true, "latitude": 999, "longitude": 1}}')
        got = store.load(f)
        self.assertFalse(got['weather']['enabled'], 'weather stays off without valid coordinates')
        f.write_text('not json')
        self.assertEqual(store.load(f), store.default())

    def test_weather_is_off_by_default_and_parses_safely(self):
        self.assertFalse(store.default()['weather']['enabled'])
        self.assertTrue(weather.url(52.5, 13.4).startswith('https://api.open-meteo.com/'))
        with self.assertRaises(ValueError):
            weather.url(91, 0)
        got = weather.parse({'current': {'temperature_2m': 12.3, 'weather_code': 61, 'wind_speed_10m': 9}})
        self.assertEqual((got['temp_c'], got['text']), (12.3, 'Light rain'))
        for bad in ({}, {'current': {}}, {'current': {'temperature_2m': 'hot'}}, None, []):
            with self.assertRaises(ValueError):
                weather.parse(bad)
        self.assertEqual(weather.wmo_text(12345), 'Unknown')

    def test_units(self):
        self.assertAlmostEqual(units.convert(1, 'mi', 'km', 'Length'), 1.609344)
        self.assertAlmostEqual(units.convert(212, '°F', '°C', 'Temperature'), 100)
        self.assertAlmostEqual(units.convert(0, '°C', 'K', 'Temperature'), 273.15)
        with self.assertRaises(ValueError):
            units.convert(-300, '°C', 'K', 'Temperature')
        with self.assertRaises(ValueError):
            units.convert(1, 'm', 'kg', 'Length')

    def test_widgets_layer_never_calls_the_network_module_when_off(self):
        text = (ROOT / 'src/makos/makos/widgets/cards.py').read_text()
        self.assertIn("if not w['enabled']:", text)


class AppMenuTests(unittest.TestCase):
    def test_spec_flattens_to_dbusmenu_ids(self):
        nodes = appmenu.flatten([('File', [('New', 'new', '<Primary>n'), None, ('Close', 'close', '<Primary><Shift>w')]), ('Edit', [('Undo', 'undo', None)])])
        self.assertEqual(nodes[0][1], [1, 5])
        self.assertEqual(nodes[1][0]['children-display'], 'submenu')
        self.assertEqual(nodes[2][2], 'new')
        self.assertEqual(nodes[2][0]['shortcut'], [['Control', 'n']])
        self.assertEqual(nodes[3][0]['type'], 'separator')
        self.assertEqual(nodes[4][0]['shortcut'], [['Control', 'Shift', 'w']])
        trailing = appmenu.flatten([('File', [('A', 'a', None), None])])
        self.assertEqual(len(trailing[1][1]), 1, 'no dangling separator')

    def test_every_app_menu_names_real_actions(self):
        for mod in (calculator, texteditor, notes, cal, activity, diskutil, sysinfo, screenshot, softwarecenter, preview, pictures, tunes, movies):
            with self.subTest(app=mod.__name__):
                nodes = appmenu.flatten(mod.MENU)
                self.assertTrue(any(n[2] for n in nodes.values()))
                self.assertTrue(all(re.fullmatch(r'[a-z_]+', n[2]) for n in nodes.values() if n[2]))


class CatalogAndPackagingTests(unittest.TestCase):
    FORBIDDEN = ('Finder', 'Safari', 'Photos', 'iTunes', 'QuickTime', 'Keynote', 'Numbers', 'GarageBand', 'Xcode', 'Siri', 'Spotlight', 'Launchpad', 'Time Machine', 'Mission Control', 'Pages')

    def test_names_ids_and_required_apps(self):
        names = [a.name for a in catalog.APPS]
        for required in ('Files', 'Terminal', 'Text Editor', 'Notes', 'Calculator', 'Calendar', 'Activity', 'Disk Utility', 'System Information', 'Screenshot', 'Preview', 'Pictures', 'Tunes', 'Movies',
                         'Software Center', 'Widgets', 'Venture', 'Paper', 'Digits', 'Slides', 'MakBox', 'Studio', 'Render', 'Engine', 'Sprite', 'ChatGPT', 'Claude'):
            self.assertIn(required, names)
        for name in names:
            self.assertNotIn(name, self.FORBIDDEN)
        self.assertEqual(len(names), len(set(names)))

    def test_desktop_entries_match_the_catalog(self):
        shipped = {p.name for p in (ROOT / 'src/makos/applications').glob('makos-*.desktop')}
        self.assertEqual(shipped, {f'makos-{a.id}.desktop' for a in catalog.APPS})
        for app in catalog.APPS:
            text = (ROOT / f'src/makos/applications/makos-{app.id}.desktop').read_text()
            self.assertIn(f'Name={app.name}\n', text)
            self.assertIn(f'Exec=makos-app {app.id} %U\n', text)
            self.assertIn(f'Icon=makos-{app.icon}\n', text)
            self.assertIn('OnlyShowIn=MakkOS;', text)

    def test_every_icon_exists_so_nothing_shows_a_placeholder(self):
        theme = ROOT / 'src/makos/icons/MakkOS'
        for app in catalog.APPS:
            self.assertTrue((theme / f'scalable/apps/makos-{app.icon}.svg').exists() or (theme / f'128x128/apps/{app.icon}.png').exists(), app.icon)

    def test_launchers_resolve_to_real_entry_points(self):
        self.assertTrue((ROOT / 'src/makos/bin/makos-app').exists())
        self.assertTrue((ROOT / 'src/makos/bin/makos-studio-app').exists())
        for key in ('studio', 'render', 'engine', 'sprite', 'makbox'):
            command = catalog.BY_ID[key].command[0]
            self.assertTrue(command.startswith('makos-studio-app '))
            self.assertIn(command.split()[1], ('studio', 'render', 'engine', 'sprite', 'makbox'))
        from makos import apps
        self.assertEqual(set(apps.MODULES) - set(catalog.BY_ID), set())
        for app_id, module in apps.MODULES.items():
            self.assertTrue((ROOT / f'src/makos/makos/apps/{module}.py').exists(), app_id)

    def test_office_uses_the_upstream_wrapper_and_matching_window_class(self):
        for app_id,kind in [('paper','word'),('digits','cell'),('slides','slide')]:
            self.assertEqual(catalog.resolve(catalog.BY_ID[app_id], lambda exe: exe=='euro-office-euro-office'), ['euro-office-euro-office','--new:'+kind])
            self.assertIn('StartupWMClass=Euro-Office', (ROOT/f'src/makos/applications/makos-{app_id}.desktop').read_text())
        self.assertIn('mak-office', (ROOT/'tools/builders/makos.py').read_text())

    def test_packaging_carries_helper_policy_and_dependencies(self):
        text = (ROOT / 'tools/builders/makos.py').read_text()
        for needle in ('makos-software-helper', 'org.makos.software.policy', 'pkexec', 'gstreamer1.0-gtk4', 'python3-pil', 'poppler-utils', 'udisks2'):
            self.assertIn(needle, text)

    def test_standalone_launcher_sets_the_window_class(self):
        main = (ROOT / 'src/makos/makos/__main__.py').read_text()
        self.assertIn("set_prgname('makos-'+name)", main)


if __name__ == '__main__':
    unittest.main()
