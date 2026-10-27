"""Settings backends and panes: every backend is exercised against tests/fakesys.py, never the real system."""
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/makos'))
sys.path.insert(0, str(ROOT / 'tests'))
from fakesys import FakeSystem, Result  # noqa: E402
from makos import common  # noqa: E402
from makos.backends import (accessibility, accounts, audio, bluetooth, datetime_, desks, displays, inputdev, language, look,  # noqa: E402
                            netman, powermgmt, printers, rewind, rootcall, security, sharing, shortcuts, startup, sysutil, updates,
                            wallpapers)
from makos.settings import model, registry  # noqa: E402

HELPER_PATH = ROOT / 'src/makos/helpers/makos-settings-helper'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home = t / 'home'
        (self.home / '.config').mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config'),
                                                'XDG_DATA_HOME': str(self.home / '.local/share'), 'XDG_STATE_HOME': str(t / 'state')})
        self.env.start()
        self.patches = [mock.patch.object(common, 'CONFIG', self.home / '.config/makos'), mock.patch.object(common, 'STATE', t / 'state/makos')]
        for p in self.patches:
            p.start()
        self.fake = FakeSystem()
        sysutil.set_runner(self.fake, self.fake.which)

    def tearDown(self):
        sysutil.set_runner(None)
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def compositor_env(self):
        return str(self.home / '.config/makos/compositor')


class ModelTests(Base):
    def test_garbage_settings_are_repaired(self):
        d = model.clean({'accent': 'chartreuse', 'font_size': 99, 'scrollbars': 'x', 'hot_corners': {'top_left': 'explode', 'nowhere': 'seek'},
                         'text_replacements': [['ok', 'fine'], ['has space', 'x'], 'bad', ['a'] * 3], 'seek_exclusions': ['rel/path', '/abs'],
                         'text_scale': 'big', 'launcher_magnify_percent': -5})
        self.assertEqual((d['accent'], d['font_size'], d['scrollbars']), ('blossom', 18, 'auto'))
        self.assertEqual(d['hot_corners'], {})
        self.assertEqual(d['text_replacements'], [['ok', 'fine']])
        self.assertEqual(d['seek_exclusions'], ['/abs'])
        self.assertEqual((d['text_scale'], d['launcher_magnify_percent']), (1.0, 0))

    def test_graphite_is_an_accent(self):
        self.assertTrue(model.clean({'accent': 'graphite'})['graphite'])
        self.assertEqual(model.clean({'graphite': True})['accent'], 'graphite')

    def test_settings_roundtrip_and_css(self):
        look.set_font_size(15)
        look.set_accent('green')
        look.set_reduce_transparency(True)
        data = common.load_settings()
        self.assertEqual((data['font_size'], data['accent'], data['reduce_transparency']), (15, 'green', True))
        css = model.css(data)
        self.assertIn('font-size: 15.0px', css)
        self.assertIn('.hero { font-size: 37.5px; }', css)
        self.assertIn('.menu-bar { background: @mk_bar; }', css)
        self.assertNotIn('font-size: 12.0px', model.css(model.clean({})))
        mode = (common.CONFIG / 'settings.json').stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


class RegistryTests(Base):
    def test_every_pane_has_a_distinct_icon_and_a_build(self):
        icons = [p.icon for p in registry.PANES]
        self.assertEqual(len(icons), len(set(icons)))
        self.assertEqual(len(registry.PANES), len({p.id for p in registry.PANES}))
        for p in registry.PANES:
            mod = importlib.import_module('makos.settings.' + p.module)
            self.assertTrue(callable(mod.build), p.id)
            svg = ROOT / f'src/makos/icons/MakkOS/scalable/apps/makos-{p.icon}.svg'
            self.assertTrue(svg.exists(), f'missing fallback vector for {p.icon}')
            self.assertIn('FALLBACK', svg.read_text())

    def test_search_and_find(self):
        self.assertEqual(registry.search('wifi')[0].id, 'network')
        self.assertEqual(registry.search('night shift')[0].id, 'displays')
        self.assertEqual(registry.find('Mouse & Trackpad').id, 'mouse')
        self.assertEqual(registry.find('bluetooth').id, 'bluetooth')
        self.assertIsNone(registry.find('nonsense'))
        self.assertEqual(registry.search(''), [])
        for forbidden in ('Mission Control', 'Spotlight', 'System Preferences', 'Time Machine'):
            self.assertFalse([p for p in registry.PANES if forbidden.lower() in p.title.lower()])


class AppearanceTests(Base):
    def test_scrollbars_and_motion_reach_toolkits_and_both_config_homes(self):
        look.set_scrollbars('always')
        self.assertEqual(self.fake.gsettings[('org.gnome.desktop.interface', 'overlay-scrolling')], 'false')
        self.assertEqual(common.load_settings()['scrollbars'], 'always')
        with self.assertRaises(ValueError):
            look.set_scrollbars('sometimes')
        look.set_reduce_motion(True)
        self.assertEqual(self.fake.config[('kdeglobals', 'KDE', 'AnimationDurationFactor')], '0')
        homes = self.fake.config_homes[('kdeglobals', 'KDE', 'AnimationDurationFactor')]
        self.assertIn(self.compositor_env(), homes)
        self.assertIn(None, homes)  # and the user's own config
        self.assertTrue(common.load_settings()['reduce_motion'])

    def test_validation(self):
        for bad in (9, 19, 'x'):
            with self.assertRaises(ValueError):
                look.set_font_size(bad)
        with self.assertRaises(ValueError):
            look.set_accent('plaid')

    def test_wallpapers(self):
        pics = self.home / 'Pictures'
        pics.mkdir()
        (pics / 'a.png').write_bytes(b'x')
        (pics / 'notes.txt').write_text('x')
        self.assertEqual([p.name for p in wallpapers.user_images()], ['a.png'])
        with self.assertRaises(ValueError):
            wallpapers.set_wallpaper(str(pics / 'notes.txt'))
        with self.assertRaises(ValueError):
            wallpapers.set_wallpaper('relative.png')
        wallpapers.set_wallpaper(str(pics / 'a.png'))
        self.assertEqual(wallpapers.current(), pics / 'a.png')
        (pics / 'a.png').unlink()
        self.assertNotEqual(wallpapers.current(), pics / 'a.png')  # falls back when the file vanished
        wallpapers.set_wallpaper('')
        self.assertEqual(common.load_settings()['wallpaper'], '')


class DesksTests(Base):
    def test_desk_count_goes_through_kwin_and_the_compositor_config(self):
        self.assertEqual(desks.count(), 4)
        r = desks.set_count(6)
        self.assertTrue(r['live'] and r['ok'])
        self.assertEqual(len(self.fake.ran('busctl', '--user', 'call', 'org.kde.KWin', '/VirtualDesktopManager', 'org.kde.KWin.VirtualDesktopManager', 'createDesktop')), 2)
        self.assertEqual(self.fake.config[('kwinrc', 'Desktops', 'Number')], '6')
        self.assertEqual(self.fake.config_homes[('kwinrc', 'Desktops', 'Number')][-1], self.compositor_env())
        desks.set_count(3)
        self.assertEqual(len(self.fake.ran('busctl', '--user', 'call', 'org.kde.KWin', '/VirtualDesktopManager', 'org.kde.KWin.VirtualDesktopManager', 'removeDesktop')), 3)
        for bad in (0, 13):
            with self.assertRaises(ValueError):
                desks.set_count(bad)

    def test_hot_corners_are_validated_stored_and_pushed_to_the_bridge(self):
        self.assertTrue(desks.set_hot_corner('top_left', 'spread'))
        self.assertEqual(common.load_settings()['hot_corners'], {'top_left': 'spread'})
        self.assertEqual(self.fake.config[('kwinrc', 'Script-makos-bridge', 'HotTopLeft')], 'spread')
        calls = ' '.join(' '.join(c) for c in self.fake.ran('busctl'))
        self.assertIn('unloadScript s makos-bridge', calls)
        self.assertIn('loadScript ss', calls)
        for corner, action in (('middle', 'seek'), ('top_left', 'rm -rf')):
            with self.assertRaises(ValueError):
                desks.set_hot_corner(corner, action)
        text = (ROOT / 'src/makos/bridge/bridge.js').read_text()
        for key in ('HotTopLeft', 'HotTopRight', 'HotBottomLeft', 'HotBottomRight', "action('spread')", "action('seek')"):
            self.assertIn(key, text)


class InputTests(Base):
    def test_repeat_is_clamped_and_written_for_kwin(self):
        self.assertEqual(inputdev.set_repeat(delay=10, rate=500), {'delay': 150, 'rate': 100})
        self.assertEqual(self.fake.config_homes[('kcminputrc', 'Keyboard', 'RepeatDelay')][-1], self.compositor_env())

    def test_layouts(self):
        inputdev.add_layout('de')
        self.assertEqual([i['layout'] for i in inputdev.layouts()], ['us', 'de'])
        self.assertEqual(self.fake.config[('kxkbrc', 'Layout', 'LayoutList')], 'us,de')
        with self.assertRaises(ValueError):
            inputdev.add_layout('de;rm')
        inputdev.remove_layout(1)
        with self.assertRaises(ValueError):
            inputdev.remove_layout(0)  # the last layout stays

    def test_modifier_remap_replaces_only_its_own_group(self):
        inputdev.set_switch_shortcut('grp:alt_shift_toggle')
        inputdev.set_modifier_remap('caps:ctrl_modifier')
        self.assertEqual(self.fake.config[('kxkbrc', 'Layout', 'Options')], 'grp:alt_shift_toggle,caps:ctrl_modifier')
        inputdev.set_modifier_remap('')
        self.assertEqual(self.fake.config[('kxkbrc', 'Layout', 'Options')], 'grp:alt_shift_toggle')
        with self.assertRaises(ValueError):
            inputdev.set_modifier_remap('caps:evil')

    def test_pointer_devices_and_changes(self):
        devs = inputdev.pointing_devices()
        pad = next(d for d in devs if d['kind'] == 'touchpad')
        self.assertTrue(pad['props']['tapToClick'])
        inputdev.set_device(pad, 'naturalScroll', False)
        self.assertFalse(self.fake.pointer['naturalScroll'])
        inputdev.set_device(pad, 'pointerAcceleration', 5)
        self.assertEqual(self.fake.pointer['pointerAcceleration'], 1.0)
        with self.assertRaises(ValueError):
            inputdev.set_device(pad, 'rm', True)
        with self.assertRaises(ValueError):
            inputdev.set_device({**pad, 'sysname': '../x'}, 'tapToClick', True)


class ShortcutTests(Base):
    def test_definitions_come_from_the_bridge_script(self):
        titles = [d['title'] for d in shortcuts.definitions()]
        for t in ('Seek', 'Spread', 'Desks', 'Tile Left', 'Close window'):
            self.assertIn(t, titles)
        self.assertEqual(shortcuts.normalise('super+space'), 'Meta+Space')
        self.assertEqual(shortcuts.normalise('ctrl+shift+f5'), 'Ctrl+Shift+F5')
        self.assertTrue(shortcuts.qt_encode('Meta+Space'))
        self.assertFalse(shortcuts.valid('Meta+Boom'))

    def test_conflict_detection_and_set(self):
        rc = self.home / '.config/makos/compositor/kglobalshortcutsrc'
        rc.parent.mkdir(parents=True)
        rc.write_text('[kwin]\nMakOS: Seek=Meta+Space,Meta+Space,Seek\nOther thing=Meta+F9,none,x\n[other]\nlaunch=Meta+F10,none,y\n')
        self.assertEqual([c['action'] for c in shortcuts.conflicts('MakOS: Spread', 'Meta+F10')], ['launch'])
        with self.assertRaises(ValueError) as ctx:
            shortcuts.set_shortcut('MakOS: Spread', 'Meta+F10')
        self.assertIn('already used', str(ctx.exception))
        with self.assertRaises(ValueError):
            shortcuts.set_shortcut('MakOS: Nope', 'Meta+F11')
        self.assertEqual(shortcuts.set_shortcut('MakOS: Spread', 'Meta+F11'), 'Meta+F11')
        call = self.fake.ran('busctl', '--user', 'call', 'org.kde.kglobalaccel')[-1]
        self.assertIn('MakOS: Spread', call)
        self.assertEqual(shortcuts.set_shortcut('MakOS: Spread', 'Meta+F10', allow_conflict=True), 'Meta+F10')

    def test_key_event_conversion(self):
        from gi.repository import Gdk
        from makos.settings import shortcuts_ui as su
        self.assertEqual(su.sequence_from_event(Gdk.KEY_space, Gdk.ModifierType.SUPER_MASK), 'Meta+Space')
        self.assertEqual(su.sequence_from_event(Gdk.KEY_comma, Gdk.ModifierType.SUPER_MASK), 'Meta+,')
        self.assertEqual(su.sequence_from_event(Gdk.KEY_Up, Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.CONTROL_MASK), 'Meta+Ctrl+Up')
        self.assertIsNone(su.sequence_from_event(Gdk.KEY_Super_L, 0))


class RootHelperTests(Base):
    def helper(self):
        loader = importlib.machinery.SourceFileLoader('makos_settings_helper', str(HELPER_PATH))
        spec = importlib.util.spec_from_loader('makos_settings_helper', loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        mod.ROOT = Path(self.tmp.name) / 'root'
        return mod

    def test_allowlist_validation(self):
        h = self.helper()
        for action, args in (('firewall-enable', []), ('apt-update', []), ('apt-upgrade', []), ('lid-action', ['suspend']), ('battery-threshold', ['80'])):
            self.assertIsNone(h.validate(action, args), action)
        bad = [('apt-update', ['x']), ('apt-upgrade', ['--allow-remove-essential']), ('dist-upgrade', []), ('lid-action', ['suspend; reboot']),
               ('lid-action', []), ('battery-threshold', ['49']), ('battery-threshold', ['101']), ('battery-threshold', ['8x']),
               ('firewall-enable', ['--force']), ('', []), ('sh', ['-c', 'id'])]
        for action, args in bad:
            self.assertIsNotNone(h.validate(action, args), (action, args))

    def test_refuses_without_root_after_validating(self):
        h = self.helper()
        with mock.patch.object(h.os, 'geteuid', return_value=1000), mock.patch('sys.stderr'):
            self.assertEqual(h.main(['h', 'apt-upgrade']), 2)
            self.assertEqual(h.main(['h', 'apt-update', 'x']), 2)
            self.assertEqual(h.main(['h']), 2)

    def test_lid_action_writes_one_dropin(self):
        h = self.helper()
        with mock.patch.object(h.os, 'geteuid', return_value=0), mock.patch('builtins.print'):
            self.assertEqual(h.main(['h', 'lid-action', 'hibernate']), 0)
        text = (h.ROOT / h.LOGIND_DROPIN).read_text()
        self.assertIn('HandleLidSwitch=hibernate', text)
        self.assertEqual(sorted(p.name for p in (h.ROOT / h.LOGIND_DROPIN).parent.iterdir()), ['50-makos-lid.conf'])
        self.assertEqual(powermgmt.lid_action(h.ROOT / h.LOGIND_DROPIN), 'hibernate')

    def test_battery_threshold_and_firewall_status(self):
        h = self.helper()
        bat = h.ROOT / 'sys/class/power_supply/BAT0'
        bat.mkdir(parents=True)
        (bat / 'charge_control_end_threshold').write_text('100\n')
        (h.ROOT / 'etc/ufw').mkdir(parents=True)
        (h.ROOT / 'etc/ufw/ufw.conf').write_text('ENABLED=yes\n')
        with mock.patch.object(h.os, 'geteuid', return_value=0), mock.patch('builtins.print') as pr:
            self.assertEqual(h.main(['h', 'battery-threshold', '80']), 0)
            self.assertEqual((bat / 'charge_control_end_threshold').read_text().strip(), '80')
            self.assertEqual(h.main(['h', 'firewall-status']), 0)
            self.assertIn('"enabled": true', pr.call_args[0][0])

    def test_firewall_and_upgrade_use_fixed_commands(self):
        h = self.helper()
        ran = []
        with mock.patch.object(h.os, 'geteuid', return_value=0), mock.patch.object(h, 'run', side_effect=lambda argv: ran.append(argv) or mock.Mock(returncode=0, stdout='ok', stderr='')), \
                mock.patch('builtins.print'):
            h.main(['h', 'firewall-enable'])
            h.main(['h', 'firewall-disable'])
        self.assertEqual(ran, [['/usr/sbin/ufw', '--force', 'enable'], ['/usr/sbin/ufw', '--force', 'disable']])
        applied = []
        with mock.patch.object(h.os, 'geteuid', return_value=0), mock.patch.object(h, 'apt', side_effect=lambda a: applied.append(a) or 0):
            self.assertEqual(h.main(['h', 'apt-update']), 0)
            self.assertEqual(h.main(['h', 'apt-upgrade']), 0)
        self.assertEqual(applied[0], ['update'])
        self.assertIn('upgrade', applied[1])
        self.assertIn('--no-remove', applied[1])
        self.assertNotIn('dist-upgrade', applied[1])

    def test_display_manager_is_restored_after_upgrade(self):
        h = self.helper()
        (h.ROOT / 'etc/X11').mkdir(parents=True)
        (h.ROOT / h.DM_FILE).write_text('/usr/sbin/sddm\n')
        before = h.dm_state()
        (h.ROOT / h.DM_FILE).write_text('/usr/sbin/gdm3\n')  # an upgrade changed it
        with mock.patch('builtins.print'):
            h.restore_display_manager(before)
        self.assertEqual((h.ROOT / h.DM_FILE).read_text().strip(), '/usr/sbin/sddm')

    def test_client_side_allowlist_and_pkexec_shape(self):
        r = rootcall.call('firewall-enable')
        self.assertEqual(self.fake.pkexec_calls[-1], [rootcall.HELPER, 'firewall-enable'])
        self.assertTrue(r['ok'])
        for action, args in (('rm', ()), ('apt-update', ('x',)), ('lid-action', ('reboot',)), ('battery-threshold', (30,)), ('battery-threshold', ('80', '90'))):
            with self.assertRaises(ValueError):
                rootcall.call(action, *args)
        self.fake.do_pkexec = lambda a, env: Result(126, '', '')
        self.assertTrue(rootcall.call('firewall-disable')['cancelled'])
        self.assertTrue(HELPER_PATH.stat().st_mode & 0o111)
        policy = (ROOT / 'src/makos/helpers/org.makos.settings.policy').read_text()
        self.assertIn('/usr/libexec/makos/makos-settings-helper', policy)
        self.assertIn('auth_admin', policy)
        self.assertNotIn('<allow_active>yes', policy)


class SecurityPowerUpdateTests(Base):
    def test_lock_settings_target_the_compositor_config(self):
        security.set_lock(auto_lock=True, timeout_min=10, grace_seconds=30)
        for key in ('Autolock', 'Timeout', 'LockGrace'):
            self.assertEqual(self.fake.config_homes[('kscreenlockerrc', 'Daemon', key)][-1], self.compositor_env())
        self.assertEqual(security.lock_settings()['timeout_min'], 10)
        with self.assertRaises(ValueError):
            security.set_lock(timeout_min=0)
        self.assertTrue(security.lock_now())
        self.assertTrue(self.fake.ran('loginctl', 'lock-session'))

    def test_firewall_goes_through_the_helper(self):
        security.set_firewall(True)
        security.set_firewall(False)
        self.assertEqual(self.fake.pkexec_calls, [[rootcall.HELPER, 'firewall-enable'], [rootcall.HELPER, 'firewall-disable']])

    def test_updates(self):
        st = updates.status()
        self.assertEqual((st['count'], st['security']), (3, 1))
        updates.refresh()
        updates.upgrade()
        self.assertEqual(self.fake.pkexec_calls, [[rootcall.HELPER, 'apt-update'], [rootcall.HELPER, 'apt-upgrade']])
        self.assertEqual(updates.ago(None), 'never')

    def test_power(self):
        b = powermgmt.battery()
        self.assertEqual((b['percent'], b['state']), (64, 'discharging'))
        self.assertEqual(powermgmt.profiles()['available'], ['power-saver', 'balanced', 'performance'])
        self.assertEqual(powermgmt.set_profile('performance'), 'performance')
        with self.assertRaises(ValueError):
            powermgmt.set_profile('turbo')
        powermgmt.set_lid_action('lock')
        self.assertEqual(self.fake.pkexec_calls[-1], [rootcall.HELPER, 'lid-action', 'lock'])
        powermgmt.set_threshold(80)
        self.assertEqual(self.fake.pkexec_calls[-1], [rootcall.HELPER, 'battery-threshold', '80'])
        with self.assertRaises(ValueError):
            powermgmt.set_threshold(10)
        self.assertFalse(powermgmt.powerdevil_running())
        with self.assertRaises(RuntimeError):
            powermgmt.set_power_options('AC', idle_minutes=5)  # honest refusal without powerdevil

    def test_battery_health_from_sysfs(self):
        bat = Path(self.tmp.name) / 'BAT0'
        bat.mkdir()
        (bat / 'energy_full').write_text('45000')
        (bat / 'energy_full_design').write_text('50000')
        self.assertEqual(powermgmt.battery_health(Path(self.tmp.name)), 90)


class AccessibilityTests(Base):
    def test_text_scale_contrast_keys_zoom(self):
        accessibility.set_text_scale(1.3)
        self.assertEqual(self.fake.gsettings[('org.gnome.desktop.interface', 'text-scaling-factor')], '1.3')
        self.assertEqual(common.load_settings()['text_scale'], 1.3)
        with self.assertRaises(ValueError):
            accessibility.set_text_scale(3)
        accessibility.set_high_contrast(True)
        self.assertTrue(common.load_settings()['high_contrast'])
        accessibility.set_keys(sticky=True, slow=True, slow_delay=99999)
        self.assertEqual(self.fake.config[('kaccessrc', 'Keyboard', 'SlowKeysDelay')], '2000')
        self.assertEqual(self.fake.config_homes[('kaccessrc', 'Keyboard', 'StickyKeys')][-1], self.compositor_env())
        accessibility.set_zoom(True, 2.5)
        self.assertTrue(self.fake.ran('busctl', '--user', 'call', 'org.kde.KWin', '/Effects', 'org.kde.kwin.Effects', 'loadEffect', 's', 'zoom'))
        with self.assertRaises(ValueError):
            accessibility.set_zoom(True, 99)

    def test_screen_reader_needs_orca(self):
        self.fake.tools.discard('orca')
        self.assertFalse(accessibility.set_screen_reader(True))
        self.fake.tools.add('orca')
        with mock.patch.object(sysutil, 'popen') as popen:
            self.assertTrue(accessibility.set_screen_reader(True))
            popen.assert_called_with(['orca'])


class LanguageDateTests(Base):
    def test_language_is_written_to_environment_d_after_validation(self):
        language.set_language('de_DE.UTF-8')
        language.set_all_formats('fr_FR.UTF-8')
        text = (self.home / '.config/environment.d/50-makos-locale.conf').read_text()
        self.assertIn('LANG=de_DE.UTF-8', text)
        self.assertIn('LC_TIME=fr_FR.UTF-8', text)
        self.assertEqual(language.user_settings()['lang'], 'de_DE.UTF-8')
        language.clear_format('LC_TIME')
        self.assertNotIn('LC_TIME', (self.home / '.config/environment.d/50-makos-locale.conf').read_text())
        for evil in ('en_US.UTF-8\nLD_PRELOAD=/tmp/x', 'x; rm', '../../etc', ''):
            with self.assertRaises(ValueError):
                language.set_language(evil)
        self.assertIn('en_GB.UTF-8', language.installed())

    def test_date_time(self):
        self.assertEqual(datetime_.status()['timezone'], 'Europe/London')
        self.assertTrue(datetime_.set_timezone('Asia/Tokyo'))
        self.assertEqual(self.fake.timezone, 'Asia/Tokyo')
        for bad in ('../etc/passwd', 'Mars/Base', 'x;y'):
            with self.assertRaises(ValueError):
                datetime_.set_timezone(bad)
        datetime_.set_ntp(False)
        self.assertFalse(self.fake.ntp)
        with self.assertRaises(ValueError):
            datetime_.set_time('tomorrow')
        datetime_.set_24h(True)
        self.assertTrue(common.load_settings()['clock_24h'])


class HardwareBackendTests(Base):
    def test_displays_apply_atomically_and_validate(self):
        outs = displays.outputs()
        self.assertEqual([o['name'] for o in outs], ['eDP-1', 'DP-2'])
        displays.apply([('eDP-1', 'scale', 1.25), ('eDP-1', 'rotation', 'left'), ('eDP-1', 'mode', '2')])
        self.assertEqual(len(self.fake.ran('kscreen-doctor', 'output.eDP-1.scale.1.25')), 1)  # one call for all three
        self.assertEqual(self.fake.outputs[0]['scale'], 1.25)
        for bad in ([('x;y', 'scale', 1)], [('eDP-1', 'scale', 9)], [('eDP-1', 'mode', 'abc')], [('eDP-1', 'rotation', 'sideways')]):
            with self.assertRaises(ValueError):
                displays.apply(bad)
        self.assertEqual(displays.snap({'x': 1700, 'y': 0, 'logical': (1920, 1080)}, [{'x': 0, 'y': 0, 'logical': (1920, 1080)}]), (1920, 0))
        displays.set_night_light(active=True, night_temp=3500, evening='21:30')
        self.assertEqual(self.fake.config[('kwinrc', 'NightColor', 'NightTemperature')], '3500')
        with self.assertRaises(ValueError):
            displays.set_night_light(evening='25:99')

    def test_audio(self):
        out = audio.devices('output')
        self.assertEqual([d['name'] for d in out], ['alsa_output.speakers', 'bluez_output.headset'])
        self.assertTrue(out[0]['default'])
        audio.set_default('output', 'bluez_output.headset')
        self.assertEqual(self.fake.default_sink, 'bluez_output.headset')
        audio.set_volume('output', 'alsa_output.speakers', 999)
        self.assertEqual(self.fake.ran('pactl', 'set-sink-volume')[-1][-1], '150%')
        with self.assertRaises(ValueError):
            audio.set_volume('output', 'bad name; rm', 10)
        self.assertEqual(audio.apps()[0]['name'], 'Music player')

    def test_bluetooth_printers_users(self):
        devs = bluetooth.devices()
        self.assertEqual([d['name'] for d in devs], ['Surface Headphones', 'Pocket Keyboard'])
        self.assertEqual(devs[0]['battery'], 72)
        with self.assertRaises(ValueError):
            bluetooth.connect('not-a-mac')
        self.assertTrue(bluetooth.connect('AA:BB:CC:DD:EE:01')['ok'])
        ps = printers.printers()
        self.assertEqual((ps[0]['name'], ps[0]['default']), ('Office_Laser', True))
        with self.assertRaises(ValueError):
            printers.set_default('x; rm')
        self.assertEqual(printers.jobs()[0]['id'], 12)
        me = accounts.current()
        self.assertEqual((me['real_name'], me['admin']), ('Ada Lovelace', True))
        accounts.set_real_name('Ada King')
        self.assertEqual(self.fake.user_name, 'Ada King')
        with self.assertRaises(ValueError):
            accounts.set_real_name('a:b')

    def test_password_is_never_handled_in_settings(self):
        self.fake.tools.add('ptyxis')
        argv = accounts.password_command()
        self.assertEqual(argv[-1], 'passwd')
        self.assertEqual(argv.count('passwd'), 1)
        # Wi-Fi: the join command for a new secured network asks nmcli for the secret in a terminal
        from makos.settings import pane_network
        self.fake.tools.add('ptyxis')
        cmd = pane_network.terminal_join_command('Cafe Guest')
        self.assertEqual(cmd[-6:-1], ['nmcli', '--ask', 'device', 'wifi', 'connect'])
        self.assertIn('--ask', cmd)
        self.assertEqual(cmd[-1], 'Cafe Guest')
        self.assertFalse(any('password' in part.lower() for part in cmd))
        with self.assertRaises(ValueError):
            pane_network.terminal_join_command('x' * 40)

    def test_network(self):
        nets = netman.wifi_list()
        self.assertEqual([n['ssid'] for n in nets], ['Home Wi-Fi', 'Cafe Guest', 'Neighbour'])
        self.assertTrue(nets[0]['connected'] and nets[0]['saved'])
        self.assertFalse(nets[1]['secured'])
        self.assertEqual(len(netman.vpns()), 1)
        with self.assertRaises(ValueError):
            netman.forget('not-a-uuid; rm')
        self.assertTrue(netman.forget('11111111-1111-1111-1111-111111111111')['ok'])
        with self.assertRaises(ValueError):
            netman.vpn_import('/etc/passwd')
        netman.set_wifi(False)
        self.assertFalse(self.fake.wifi)
        self.assertFalse([c for c in self.fake.calls if c[0] == 'nmcli' and ('connect' in c or 'wifi-sec.psk' in c)])  # no secret-bearing call

    def test_sharing_startup_rewind(self):
        names = {s['id']: s for s in sharing.status()}
        self.assertTrue(names['samba']['installed'])
        self.assertFalse(names['rdp']['installed'])
        with self.assertRaises(ValueError):
            sharing.set_user_service('sshd.service', True)
        self.assertFalse(startup.theme_switch_status()['available'])
        self.assertIn('not available yet', startup.theme_switch_status()['reason'])
        self.assertFalse(rewind.status()['implemented'])
        self.assertIn('does not create or restore backups', rewind.status()['message'])

    def test_login_items(self):
        auto = self.home / '.config/autostart'
        auto.mkdir(parents=True)
        (auto / 'syncthing.desktop').write_text('[Desktop Entry]\nType=Application\nName=Sync\nExec=syncthing\n')
        items = {i['id']: i for i in startup.login_items()}
        self.assertTrue(items['syncthing.desktop']['enabled'])
        startup.set_item_enabled('syncthing.desktop', False)
        self.assertFalse({i['id']: i for i in startup.login_items()}['syncthing.desktop']['enabled'])  # still listed so it can be switched back on
        startup.set_item_enabled('syncthing.desktop', True)
        self.assertTrue({i['id']: i for i in startup.login_items()}['syncthing.desktop']['enabled'])
        for bad in ('../x.desktop', 'a b.desktop', 'x'):
            with self.assertRaises(ValueError):
                startup.set_item_enabled(bad, True)


class AutostartTests(Base):
    def test_only_entries_for_this_desktop_are_listed(self):
        self.assertTrue(startup.applies({}, 'MakkOS'))
        self.assertTrue(startup.applies({'OnlyShowIn': 'KDE;MakkOS;'}, 'MakkOS'))
        self.assertFalse(startup.applies({'OnlyShowIn': 'KDE;'}, 'MakkOS'))
        self.assertFalse(startup.applies({'NotShowIn': 'MakkOS;'}, 'MakkOS'))
        self.assertTrue(startup.applies({'OnlyShowIn': 'KDE;'}, 'KDE'))


class NoApplePhrasesTests(unittest.TestCase):
    def test_visible_strings_do_not_use_forbidden_names(self):
        bad = ('Spotlight', 'Mission Control', 'System Preferences', 'Time Machine', 'Finder', 'Launchpad', 'macOS', 'Siri', 'Command ⌘', '⌘')
        for base in ('src/makos/makos/settings', 'src/makos/makos/seek'):
            for path in (ROOT / base).rglob('*.py'):
                text = path.read_text()
                for word in bad:
                    self.assertNotIn(word, text, f'{path} mentions {word}')


if __name__ == '__main__':
    unittest.main()
