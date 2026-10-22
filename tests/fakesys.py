"""A fake operating system for the settings backends: one runner for `sysutil.set_runner()` that answers kreadconfig6,
kwriteconfig6, kscreen-doctor, pactl, nmcli, busctl, lpstat, timedatectl, powerprofilesctl, systemctl, apt, gsettings, pkexec...
with canned, mutable state. Used by tests/test_makos_settings.py and by the screenshot rig, so nothing touches the real system.
"""
import json
from collections import namedtuple

Result = namedtuple('Result', 'code out err')
OK = Result(0, '', '')
FAIL = Result(1, '', 'fake: not available')

TOOLS = {'kreadconfig6', 'kwriteconfig6', 'kscreen-doctor', 'pactl', 'nmcli', 'busctl', 'lpstat', 'lpoptions', 'timedatectl', 'localectl',
         'powerprofilesctl', 'systemctl', 'apt', 'gsettings', 'pkexec', 'loginctl', 'hostname', 'tinysparql', 'wn', 'locale', 'bluetoothctl',
         'cancel', 'lp', 'df', 'orca', 'fc-list'}


def _unit(v, t='s'):
    return {'type': t, 'data': v}


class FakeSystem:
    def __init__(self, tools=None):
        self.calls = []            # every argv, in order
        self.envs = []             # env passed with each call
        self.config = {}           # (file, group, key) -> value
        self.gsettings = {}
        self.tools = set(tools if tools is not None else TOOLS)
        self.outputs = [
            {'name': 'eDP-1', 'enabled': True, 'connected': True, 'priority': 1, 'scale': 1.5, 'rotation': 1, 'pos': {'x': 0, 'y': 0},
             'currentModeId': '1', 'sizeMM': {'width': 300, 'height': 200},
             'modes': [{'id': '1', 'size': {'width': 2880, 'height': 1920}, 'refreshRate': 120.0},
                       {'id': '2', 'size': {'width': 2880, 'height': 1920}, 'refreshRate': 60.0},
                       {'id': '3', 'size': {'width': 1920, 'height': 1280}, 'refreshRate': 60.0}]},
            {'name': 'DP-2', 'enabled': True, 'connected': True, 'priority': 2, 'scale': 1.0, 'rotation': 1, 'pos': {'x': 1920, 'y': 0},
             'currentModeId': '10', 'modes': [{'id': '10', 'size': {'width': 2560, 'height': 1440}, 'refreshRate': 60.0}]}]
        self.sinks = [{'name': 'alsa_output.speakers', 'description': 'Built-in Speakers', 'volume': {'front-left': {'value_percent': '55%'}, 'front-right': {'value_percent': '55%'}},
                       'mute': False, 'ports': [], 'active_port': None, 'properties': {}},
                      {'name': 'bluez_output.headset', 'description': 'Surface Headphones', 'volume': {'front-left': {'value_percent': '30%'}, 'front-right': {'value_percent': '30%'}},
                       'mute': False, 'ports': [], 'active_port': None, 'properties': {}}]
        self.default_sink = 'alsa_output.speakers'
        self.sources = [{'name': 'alsa_input.mic', 'description': 'Built-in Microphone', 'volume': {'mono': {'value_percent': '70%'}}, 'mute': False,
                         'ports': [], 'active_port': None, 'properties': {}, 'monitor_source': ''}]
        self.sink_inputs = [{'index': 7, 'volume': {'front-left': {'value_percent': '80%'}}, 'mute': False,
                             'properties': {'application.name': 'Music player'}}]
        self.profile = 'balanced'
        self.ntp = True
        self.timezone = 'Europe/London'
        self.wifi = True
        self.printers = True
        self.services = {'smbd.service': 'inactive'}
        self.pkexec_calls = []
        self.user_name = 'Ada Lovelace'
        self.pointer = {'tapToClick': True, 'naturalScroll': True, 'pointerAcceleration': 0.0, 'disableWhileTyping': True, 'leftHanded': False,
                        'scrollFactor': 1.0, 'pointerAccelerationProfileFlat': False}

    # ---- plumbing
    def which(self, tool):
        return f'/usr/bin/{tool}' if tool in self.tools else None

    def __call__(self, argv, timeout=5, input=None, env=None):  # noqa: A002
        self.calls.append(list(argv))
        self.envs.append(env)
        head = argv[0]
        fn = getattr(self, 'do_' + head.replace('-', '_'), None)
        if head not in self.tools or fn is None:
            return Result(127, '', 'not found')
        out = fn(argv[1:], env or {})
        return out if isinstance(out, Result) else Result(0, out, '')

    def ran(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]

    # ---- KDE config
    def do_kreadconfig6(self, a, env):
        f, groups, key, default = self._kparse(a)
        return self.config.get((f, groups, key), default)

    def do_kwriteconfig6(self, a, env):
        f, groups, key, rest = self._kparse(a, write=True)
        self.config[(f, groups, key)] = rest
        self.config_homes = getattr(self, 'config_homes', {})
        self.config_homes.setdefault((f, groups, key), []).append((env or {}).get('XDG_CONFIG_HOME'))
        return ''

    @staticmethod
    def _kparse(a, write=False):
        f, groups, key, default, rest = '', [], '', '', ''
        i = 0
        while i < len(a):
            if a[i] == '--file':
                f = a[i + 1]
                i += 2
            elif a[i] == '--group':
                groups.append(a[i + 1])
                i += 2
            elif a[i] == '--key':
                key = a[i + 1]
                i += 2
            elif a[i] == '--default':
                default = a[i + 1]
                i += 2
            else:
                rest = a[i]
                i += 1
        return (f, '][' .join(groups), key, rest) if write else (f, '][' .join(groups), key, default)

    def do_gsettings(self, a, env):
        if a[0] == 'set':
            self.gsettings[(a[1], a[2])] = a[3]
            return ''
        return self.gsettings.get((a[1], a[2]), "'default'")

    # ---- displays
    def do_kscreen_doctor(self, a, env):
        if a == ['-j']:
            return json.dumps({'outputs': self.outputs})
        for item in a:
            parts = item.split('.')
            if parts[0] != 'output':
                continue
            out = next((o for o in self.outputs if o['name'] == parts[1]), None)
            if not out:
                return FAIL
            if parts[2] == 'scale':
                out['scale'] = float('.'.join(parts[3:]))
            elif parts[2] == 'mode':
                out['currentModeId'] = parts[3]
            elif parts[2] == 'rotation':
                out['rotation'] = {'none': 1, 'left': 2, 'inverted': 4, 'right': 8}[parts[3]]
            elif parts[2] == 'position':
                x, y = parts[3].split(',')
                out['pos'] = {'x': int(x), 'y': int(y)}
            elif parts[2] == 'priority':
                for o in self.outputs:
                    o['priority'] = 1 if o is out else 2
        return ''

    # ---- audio
    def do_pactl(self, a, env):
        if a[0] == 'get-default-sink':
            return self.default_sink
        if a[0] == 'get-default-source':
            return self.sources[0]['name']
        if a[:3] == ['-f', 'json', 'list']:
            return json.dumps({'sinks': self.sinks, 'sources': self.sources, 'sink-inputs': self.sink_inputs, 'source-outputs': []}[a[3]])
        if a[0] == 'set-default-sink':
            self.default_sink = a[1]
        elif a[0] == 'set-sink-volume':
            s = next(x for x in self.sinks if x['name'] == a[1])
            s['volume'] = {f'c{i}': {'value_percent': v} for i, v in enumerate(a[2:])}
        elif a[0] == 'set-sink-mute':
            next(x for x in self.sinks if x['name'] == a[1])['mute'] = a[2] == '1'
        elif a[0] == 'set-sink-input-volume':
            self.sink_inputs[0]['volume'] = {'front-left': {'value_percent': a[2]}}
        return ''

    # ---- network
    def do_nmcli(self, a, env):
        if a[:3] == ['-t', 'general', 'status'] or (a[:2] == ['-t', '-f'] and 'general' in a):
            return f"connected:full:{'enabled' if self.wifi else 'disabled'}:enabled"
        if 'device' in a and 'wifi' in a and 'list' in a:
            return '*:Home Wi-Fi:82:WPA2:36:540 Mbit/s\n :Cafe Guest:61::6:130 Mbit/s\n :Neighbour:44:WPA2:11:130 Mbit/s'
        if a[-1] == 'device' or a[-2:] == ['device', 'status'] or 'DEVICE,TYPE,STATE,CONNECTION' in a:
            return 'wlan0:wifi:connected:Home Wi-Fi\neth0:ethernet:unavailable:'
        if 'connection' in a and 'show' in a and 'NAME,UUID,TYPE,DEVICE,AUTOCONNECT' in a:
            return 'Home Wi-Fi:11111111-1111-1111-1111-111111111111:802-11-wireless:wlan0:yes\nWork VPN:22222222-2222-2222-2222-222222222222:wireguard::no'
        if a[:2] == ['radio', 'wifi']:
            if len(a) == 3:
                self.wifi = a[2] == 'on'
            return 'enabled' if self.wifi else 'disabled'
        return ''

    # ---- print
    def do_lpstat(self, a, env):
        return {'-r': 'scheduler is running', '-d': 'system default destination: Office_Laser', '-v': 'device for Office_Laser: ipp://printer.local/ipp/print',
                '-p': 'printer Office_Laser is idle.  enabled since Mon', '-o': 'Office_Laser-12 ada 2048 Thu 22 Oct'}.get(a[0], '')

    def do_lpoptions(self, a, env):
        return ''

    # ---- time, language, power, services
    def do_timedatectl(self, a, env):
        if a[0] == 'show':
            return f"Timezone={self.timezone}\nNTP={'yes' if self.ntp else 'no'}\nCanNTP=yes\nNTPSynchronized=yes\nLocalRTC=no\nTimeUSec=Thu 2026-10-22 14:30:00 BST"
        if a[0] == 'list-timezones':
            return 'Europe/London\nEurope/Paris\nAmerica/New_York\nAsia/Tokyo'
        if a[0] == 'set-timezone':
            self.timezone = a[1]
        if a[0] == 'set-ntp':
            self.ntp = a[1] == 'true'
        return ''

    def do_localectl(self, a, env):
        return 'System Locale: LANG=en_GB.UTF-8'

    def do_locale(self, a, env):
        return 'C\nen_GB.utf8\nen_US.utf8\nde_DE.utf8\nfr_FR.utf8\nPOSIX'

    def do_powerprofilesctl(self, a, env):
        if a[0] == 'list':
            return '  power-saver:\n* balanced:\n  performance:'
        if a[0] == 'get':
            return self.profile
        if a[0] == 'set':
            self.profile = a[1]
        return ''

    def do_systemctl(self, a, env):
        unit = a[-1]
        if 'LoadState' in a:
            return 'loaded' if unit in ('smbd.service', 'ssh.service', 'avahi-daemon.service') else 'not-found'
        if a[-2:-1] == ['is-active'] or 'is-active' in a:
            return self.services.get(unit, 'inactive')
        if 'is-enabled' in a:
            return 'disabled'
        return ''

    def do_hostname(self, a, env):
        return 'surface-makos'

    def do_loginctl(self, a, env):
        return ''

    def do_apt(self, a, env):
        return ('Listing...\nlibc6/noble-updates 2.40-1 arm64 [upgradable from: 2.39-1]\n'
                'openssl/noble-security 3.3.2 arm64 [upgradable from: 3.3.1]\nmakos-shell/stable 0.1.1 arm64 [upgradable from: 0.1.0]')

    def do_pkexec(self, a, env):
        self.pkexec_calls.append(a)
        return Result(0, '{"ok": true}', '')

    def do_df(self, a, env):
        return 'Filesystem Type 1B-blocks Used Available Mounted on\n/dev/nvme0n1p2 ext4 500000000000 200000000000 300000000000 /'

    def do_tinysparql(self, a, env):
        return Result(1, '', 'Could not activate remote peer')

    # ---- busctl: BlueZ, AccountsService, KWin, UPower
    def do_busctl(self, a, env):
        text = ' '.join(a)
        if 'org.bluez' in text and 'GetManagedObjects' in text:
            dev = {'org.bluez.Device1': {'Address': _unit('AA:BB:CC:DD:EE:01'), 'Alias': _unit('Surface Headphones'), 'Icon': _unit('audio-headphones'),
                                         'Paired': _unit(True, 'b'), 'Connected': _unit(True, 'b'), 'Trusted': _unit(True, 'b')},
                   'org.bluez.Battery1': {'Percentage': _unit(72, 'y')}}
            dev2 = {'org.bluez.Device1': {'Address': _unit('AA:BB:CC:DD:EE:02'), 'Alias': _unit('Pocket Keyboard'), 'Icon': _unit('input-keyboard'),
                                          'Paired': _unit(False, 'b'), 'Connected': _unit(False, 'b'), 'Trusted': _unit(False, 'b')}}
            ad = {'org.bluez.Adapter1': {'Alias': _unit('makos-laptop'), 'Address': _unit('00:11:22:33:44:55'), 'Powered': _unit(True, 'b'),
                                         'Discoverable': _unit(False, 'b'), 'Discovering': _unit(False, 'b')}}
            data = {'/org/bluez/hci0': ad, '/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01': dev, '/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02': dev2}
            return json.dumps({'type': 'a{oa{sa{sv}}}', 'data': [{k: {i: {p: v for p, v in props.items()} for i, props in v.items()} for k, v in data.items()}]})
        if 'FindUserById' in text:
            return json.dumps({'type': 'o', 'data': ['/org/freedesktop/Accounts/User1000']})
        if 'org.freedesktop.Accounts.User' in text and 'GetAll' in text:
            props = {'UserName': _unit('ada'), 'RealName': _unit(self.user_name), 'IconFile': _unit(''), 'AccountType': _unit(1, 'i'),
                     'AutomaticLogin': _unit(False, 'b'), 'Locked': _unit(False, 'b'), 'Language': _unit('en_GB.UTF-8')}
            return json.dumps({'type': 'a{sv}', 'data': [props]})
        if 'SetRealName' in text:
            self.user_name = a[-1]
            return ''
        if 'org.freedesktop.UPower' in text and 'GetAll' in text:
            props = {'IsPresent': _unit(True, 'b'), 'Percentage': _unit(64.0, 'd'), 'State': _unit(2, 'u'), 'TimeToEmpty': _unit(10800, 'x'), 'TimeToFull': _unit(0, 'x')}
            return json.dumps({'type': 'a{sv}', 'data': [props]})
        if 'org.kde.Solid.PowerManagement' in text:
            return FAIL  # powerdevil is not running in the MakOS session
        if 'InputDeviceManager' in text and 'devicesSysNames' in text:
            return 'as 2 "event3" "event4"'
        if '/org/kde/KWin/InputDevice/' in text and 'get-property' in text:
            dev = a[-3].rsplit('/', 1)[-1]
            prop = a[-1]
            if prop == 'pointer':
                return 'b true'
            if prop == 'touchpad':
                return 'b ' + ('true' if dev == 'event3' else 'false')
            if prop == 'tabletTool':
                return 'b false'
            if prop == 'name':
                return 's "Surface Type Cover Touchpad"' if dev == 'event3' else 's "USB Mouse"'
            if prop in ('vendor', 'product'):
                return 'u 1118'
            if prop in self.pointer:
                v = self.pointer[prop]
                return ('b ' + str(v).lower()) if isinstance(v, bool) else f'd {v}'
            if prop.startswith('supports'):
                return 'b true'
            return FAIL
        if 'set-property' in text and '/org/kde/KWin/InputDevice/' in text:
            self.pointer[a[-3]] = a[-1] == 'true' if a[-2] == 'b' else float(a[-1])
            return ''
        if 'VirtualDesktopManager' in text and 'get-property' in text:
            ids = getattr(self, 'desk_ids', None) or [f'0000000{i}-0000-0000-0000-000000000000' for i in range(1, 5)]
            self.desk_ids = ids
            return 'a(uss) %d ' % len(ids) + ' '.join(f'{i} "{d}" "Desk {i + 1}"' for i, d in enumerate(ids))
        if 'createDesktop' in text:
            self.desk_ids.append('0000009%d-0000-0000-0000-000000000000' % len(self.desk_ids))
            return ''
        if 'removeDesktop' in text:
            self.desk_ids.remove(a[-1])
            return ''
        if 'NightLight' in text and 'available' in text:
            return 'b true'
        if 'NightLight' in text and 'currentTemperature' in text:
            return 'u 6500'
        if 'isEffectLoaded' in text:
            return 'b false'
        return ''
