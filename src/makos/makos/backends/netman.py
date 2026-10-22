"""Network settings backend: NetworkManager over D-Bus (secrets) with `nmcli` for everything that carries no secret.

Passwords never appear in argv, logs or return values: a Wi-Fi/hotspot passphrase is handed to NetworkManager
through its D-Bus API (AddAndActivateConnection / AddConnection). If D-Bus is unavailable, `nmcli --ask` is used and
the passphrase goes over the child's stdin. Tests inject a fake bus with `set_bus()`.
"""
import ipaddress
import re
import uuid as uuidlib
from pathlib import Path

from . import sysutil

SSID_MAX = 32
NAME_OK = re.compile(r'^[^\x00-\x1f]{1,64}$')
HOTSPOT_NAME = 'Amerika Hotspot'

_bus = None


def set_bus(bus):
    """Install a fake NetworkManager bus (tests). The real one is created lazily on first use."""
    global _bus
    _bus = bus


class NMBus:
    """Minimal NetworkManager D-Bus client (Gio). Every method returns plain Python or raises RuntimeError."""
    NM = 'org.freedesktop.NetworkManager'

    def __init__(self):
        import gi
        gi.require_version('Gio', '2.0')
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def _call(self, path, iface, method, params=None, sig=None):
        try:
            return self.conn.call_sync(self.NM, path, iface, method, params, None, self.Gio.DBusCallFlags.NONE, 15000, None)
        except self.GLib.Error as error:
            raise RuntimeError(error.message) from None

    def _prop(self, path, iface, name):
        res = self._call(path, 'org.freedesktop.DBus.Properties', 'Get', self.GLib.Variant('(ss)', (iface, name)))
        return res.unpack()[0]

    def wifi_device(self):
        for dev in self._call('/org/freedesktop/NetworkManager', self.NM, 'GetDevices').unpack()[0]:
            if self._prop(dev, 'org.freedesktop.NetworkManager.Device', 'DeviceType') == 2:
                return dev
        return None

    def access_point(self, device, ssid):
        for ap in self._call(device, 'org.freedesktop.NetworkManager.Device.Wireless', 'GetAccessPoints').unpack()[0]:
            raw = bytes(self._prop(ap, 'org.freedesktop.NetworkManager.AccessPoint', 'Ssid'))
            if raw.decode('utf-8', 'replace') == ssid:
                return ap
        return '/'

    def _variant_settings(self, settings):
        GLib = self.GLib

        def wrap(v):
            if isinstance(v, bool):
                return GLib.Variant('b', v)
            if isinstance(v, int):
                return GLib.Variant('u' if v >= 0 else 'i', v)
            if isinstance(v, bytes):
                return GLib.Variant('ay', v)
            if isinstance(v, list):
                return GLib.Variant('as', v)
            return GLib.Variant('s', str(v))
        return GLib.Variant('a{sa{sv}}', {sec: {k: wrap(v) for k, v in vals.items()} for sec, vals in settings.items()})

    def add_and_activate(self, settings, device, ap):
        params = self.GLib.Variant.new_tuple(self._variant_settings(settings), self.GLib.Variant('o', device), self.GLib.Variant('o', ap or '/'))
        self._call('/org/freedesktop/NetworkManager', self.NM, 'AddAndActivateConnection', params)

    def add_connection(self, settings):
        params = self.GLib.Variant.new_tuple(self._variant_settings(settings))
        return self._call('/org/freedesktop/NetworkManager/Settings', 'org.freedesktop.NetworkManager.Settings', 'AddConnection', params).unpack()[0]

    def activate(self, conn_path, device='/'):
        params = self.GLib.Variant('(ooo)', (conn_path, device, '/'))
        self._call('/org/freedesktop/NetworkManager', self.NM, 'ActivateConnection', params)


def bus():
    global _bus
    if _bus is None:
        try:
            _bus = NMBus()
        except Exception as error:  # noqa: BLE001 - no system bus (rig, containers)
            raise RuntimeError(f'NetworkManager D-Bus unavailable: {error}') from None
    return _bus


# ---------------------------------------------------------------- status
def available():
    return sysutil.have('nmcli') and sysutil.run(['nmcli', '-t', 'general', 'status']).code == 0


def status():
    res = sysutil.run(['nmcli', '-t', '-f', 'STATE,CONNECTIVITY,WIFI,WWAN', 'general'])
    f = sysutil.split_nmcli(res.out.splitlines()[0]) if res.code == 0 and res.out else []
    f += [''] * (4 - len(f))
    devs = devices()
    active = next((d for d in devs if d['state'] == 'connected' and d['type'] in ('wifi', 'ethernet')), None)
    return {'available': res.code == 0, 'state': f[0] or 'unknown', 'connectivity': f[1] or 'unknown', 'wifi_enabled': f[2] == 'enabled',
            'airplane': airplane_mode(), 'connection': active['connection'] if active else None, 'type': active['type'] if active else None}


def devices():
    res = sysutil.run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device'])
    out = []
    for line in res.out.splitlines():
        f = sysutil.split_nmcli(line) + ['', '', '', '']
        out.append({'device': f[0], 'type': f[1], 'state': f[2], 'connection': f[3] or None})
    return out


# ---------------------------------------------------------------- Wi-Fi
def security_kind(sec):
    s = (sec or '').upper()
    if not s or s == '--':
        return 'open'
    if 'SAE' in s:
        return 'wpa3'
    if 'WPA' in s:
        return 'wpa'
    if 'WEP' in s:
        return 'wep'
    if '802.1X' in s:
        return 'enterprise'
    return 'wpa'


def wifi_list():
    """Visible networks, strongest first, one row per SSID. `saved` marks networks with a stored profile."""
    res = sysutil.run(['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY,CHAN,RATE', 'device', 'wifi', 'list'], timeout=10)
    if res.code != 0:
        return []
    saved = {c['name'] for c in connections() if c['type'] == '802-11-wireless'}
    best = {}
    for line in res.out.splitlines():
        f = sysutil.split_nmcli(line) + [''] * 6
        ssid = f[1]
        if not ssid:
            continue
        signal = int(f[2]) if f[2].isdigit() else 0
        net = {'ssid': ssid, 'signal': signal, 'security': f[3], 'kind': security_kind(f[3]), 'secured': security_kind(f[3]) != 'open',
               'connected': f[0].strip() == '*', 'channel': f[4], 'rate': f[5], 'saved': ssid in saved}
        old = best.get(ssid)
        if not old or net['connected'] or (not old['connected'] and signal > old['signal']):
            best[ssid] = net
    return sorted(best.values(), key=lambda n: (not n['connected'], -n['signal'], n['ssid'].lower()))


def scan():
    return sysutil.run(['nmcli', 'device', 'wifi', 'rescan'], timeout=10).code == 0


def set_wifi(on):
    sysutil.run(['nmcli', 'radio', 'wifi', 'on' if on else 'off'])
    return sysutil.run(['nmcli', 'radio', 'wifi']).out == 'enabled'


def _wifi_security(kind, password):
    if kind == 'open' or not password:
        return {}
    if kind == 'wep':
        return {'802-11-wireless-security': {'key-mgmt': 'none', 'wep-key0': password, 'wep-key-type': 1}}
    if kind == 'wpa3':
        return {'802-11-wireless-security': {'key-mgmt': 'sae', 'psk': password}}
    return {'802-11-wireless-security': {'key-mgmt': 'wpa-psk', 'psk': password}}


def check_ssid(ssid):
    if not ssid or len(ssid.encode('utf-8')) > SSID_MAX or '\x00' in ssid:
        raise ValueError('The network name must be 1 to 32 bytes long.')
    return ssid


def check_password(kind, password):
    if kind in ('wpa', 'wpa3') and not (8 <= len(password) <= 63):
        raise ValueError('A WPA password must be 8 to 63 characters.')
    return password


def join(ssid, password=None, hidden=False, kind=None):
    """Join (and save) a network. Saved networks reconnect without a password. Returns {'ok': bool, 'error': str|None}."""
    ssid = check_ssid(ssid)
    existing = next((c for c in connections() if c['type'] == '802-11-wireless' and c['name'] == ssid), None)
    if existing and not password:
        return connect_saved(existing['uuid'])
    kind = kind or ('wpa' if password else 'open')
    if password:
        check_password(kind, password)
    settings = {'connection': {'id': ssid, 'type': '802-11-wireless', 'uuid': str(uuidlib.uuid4()), 'autoconnect': True},
                '802-11-wireless': {'ssid': ssid.encode('utf-8'), 'mode': 'infrastructure', 'hidden': bool(hidden)},
                'ipv4': {'method': 'auto'}, 'ipv6': {'method': 'auto'}}
    settings.update(_wifi_security(kind, password))
    try:
        b = bus()
        device = b.wifi_device()
        if not device:
            return {'ok': False, 'error': 'No Wi-Fi adapter found.'}
        b.add_and_activate(settings, device, b.access_point(device, ssid))
        return {'ok': True, 'error': None}
    except RuntimeError as error:
        if 'unavailable' not in str(error):
            return {'ok': False, 'error': _scrub(str(error), password)}
    # D-Bus unavailable: nmcli prompts for the secret on stdin (--ask), so it never reaches argv
    argv = ['nmcli', '--ask', 'device', 'wifi', 'connect', ssid] + (['hidden', 'yes'] if hidden else [])
    res = sysutil.run(argv, timeout=45, input=(password + '\n') if password else None)
    return {'ok': res.code == 0, 'error': None if res.code == 0 else _scrub(res.err or res.out, password)}


def _scrub(text, secret):
    text = text or ''
    if secret:
        text = text.replace(secret, '***')
    return text[:300]


# ---------------------------------------------------------------- saved profiles (Wi-Fi, wired, VPN)
def connections():
    res = sysutil.run(['nmcli', '-t', '-f', 'NAME,UUID,TYPE,DEVICE,AUTOCONNECT', 'connection', 'show'])
    out = []
    for line in res.out.splitlines():
        f = sysutil.split_nmcli(line) + [''] * 5
        out.append({'name': f[0], 'uuid': f[1], 'type': f[2], 'device': f[3] or None, 'active': bool(f[3]), 'autoconnect': f[4] == 'yes'})
    return out


def _check_uuid(value):
    try:
        return str(uuidlib.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ValueError('Not a valid connection id.') from None


def connect_saved(uuid):
    res = sysutil.run(['nmcli', 'connection', 'up', 'uuid', _check_uuid(uuid)], timeout=45)
    return {'ok': res.code == 0, 'error': None if res.code == 0 else res.err[:300]}


def disconnect(uuid):
    res = sysutil.run(['nmcli', 'connection', 'down', 'uuid', _check_uuid(uuid)], timeout=20)
    return {'ok': res.code == 0, 'error': None if res.code == 0 else res.err[:300]}


def forget(uuid):
    res = sysutil.run(['nmcli', 'connection', 'delete', 'uuid', _check_uuid(uuid)], timeout=15)
    return {'ok': res.code == 0, 'error': None if res.code == 0 else res.err[:300]}


def set_autoconnect(uuid, on):
    return sysutil.run(['nmcli', 'connection', 'modify', 'uuid', _check_uuid(uuid), 'connection.autoconnect', 'yes' if on else 'no']).code == 0


def wired():
    """Ethernet devices with their profile and addressing."""
    out = []
    for d in devices():
        if d['type'] != 'ethernet':
            continue
        res = sysutil.run(['nmcli', '-t', '-f', 'IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,GENERAL.HWADDR', 'device', 'show', d['device']])
        info = {}
        for line in res.out.splitlines():
            f = sysutil.split_nmcli(line)
            info.setdefault(re.sub(r'\[\d+\]$', '', f[0]), f[1] if len(f) > 1 else '')
        out.append({**d, 'ip': info.get('IP4.ADDRESS', ''), 'gateway': info.get('IP4.GATEWAY', ''), 'dns': info.get('IP4.DNS', '')})
    return out


# ---------------------------------------------------------------- VPN
VPN_TYPES = ('vpn', 'wireguard')


def vpns():
    return [c for c in connections() if c['type'] in VPN_TYPES]


def vpn_kind(path):
    name = Path(path).name.lower()
    if name.endswith('.conf'):
        return 'wireguard'
    if name.endswith('.ovpn'):
        return 'openvpn'
    raise ValueError('Choose a WireGuard (.conf) or OpenVPN (.ovpn) profile.')


def vpn_import(path):
    kind = vpn_kind(path)
    p = Path(path)
    if not p.is_file() or p.stat().st_size > 1_000_000:
        raise ValueError('That file cannot be used as a VPN profile.')
    res = sysutil.run(['nmcli', 'connection', 'import', 'type', kind, 'file', str(p)], timeout=20)
    return {'ok': res.code == 0, 'kind': kind, 'error': None if res.code == 0 else res.err[:300]}


def vpn_toggle(uuid, on):
    return connect_saved(uuid) if on else disconnect(uuid)


# ---------------------------------------------------------------- hotspot
def hotspot_active():
    return any(c['name'] == HOTSPOT_NAME and c['active'] for c in connections())


def hotspot_start(ssid, password):
    ssid = check_ssid(ssid)
    if not 8 <= len(password) <= 63:
        raise ValueError('The hotspot password must be 8 to 63 characters.')
    settings = {'connection': {'id': HOTSPOT_NAME, 'type': '802-11-wireless', 'uuid': str(uuidlib.uuid4()), 'autoconnect': False},
                '802-11-wireless': {'ssid': ssid.encode('utf-8'), 'mode': 'ap', 'band': 'bg'},
                '802-11-wireless-security': {'key-mgmt': 'wpa-psk', 'psk': password},
                'ipv4': {'method': 'shared'}, 'ipv6': {'method': 'ignore'}}
    for c in connections():  # replace an older hotspot profile so there is always exactly one
        if c['name'] == HOTSPOT_NAME:
            forget(c['uuid'])
    try:
        b = bus()
        device = b.wifi_device()
        if not device:
            return {'ok': False, 'error': 'No Wi-Fi adapter found.'}
        b.add_and_activate(settings, device, '/')
        return {'ok': True, 'error': None}
    except RuntimeError as error:
        return {'ok': False, 'error': _scrub(str(error), password)}


def hotspot_stop():
    for c in connections():
        if c['name'] == HOTSPOT_NAME and c['active']:
            return disconnect(c['uuid'])
    return {'ok': True, 'error': None}


# ---------------------------------------------------------------- airplane mode
def airplane_mode():
    res = sysutil.run(['nmcli', 'radio', 'all'])
    return res.code == 0 and 'disabled' in res.out.split() and 'enabled' not in res.out.split()


def set_airplane(on):
    sysutil.run(['nmcli', 'radio', 'all', 'off' if on else 'on'])
    if sysutil.have('rfkill'):
        sysutil.run(['rfkill', 'block' if on else 'unblock', 'bluetooth'])
    return airplane_mode()


# ---------------------------------------------------------------- proxy (GNOME gsettings and KDE kioslaverc, both kept in step)
PROXY_MODES = ('none', 'manual', 'auto')
_KDE_TYPE = {'none': '0', 'manual': '1', 'auto': '2'}


def _host_ok(host):
    return bool(re.fullmatch(r'[A-Za-z0-9._:\-\[\]]{1,253}', host or ''))


def proxy_get():
    mode = sysutil.gsettings_get('org.gnome.system.proxy', 'mode', "'none'").strip("'")
    if mode not in PROXY_MODES:
        mode = 'none'
    kde = sysutil.kread('kioslaverc', 'Proxy Settings', 'ProxyType', '0')
    if mode == 'none' and kde in ('1', '2'):
        mode = 'manual' if kde == '1' else 'auto'
    out = {'mode': mode, 'http_host': '', 'http_port': 0, 'socks_host': '', 'socks_port': 0, 'pac_url': '', 'no_proxy': ''}
    http = sysutil.kread('kioslaverc', 'Proxy Settings', 'httpProxy', '')
    if http:
        m = re.match(r'^(?:\w+://)?([^:\s]+)[: ](\d+)$', http)
        if m:
            out['http_host'], out['http_port'] = m.group(1), int(m.group(2))
    socks = sysutil.kread('kioslaverc', 'Proxy Settings', 'socksProxy', '')
    m = re.match(r'^(?:\w+://)?([^:\s]+)[: ](\d+)$', socks or '')
    if m:
        out['socks_host'], out['socks_port'] = m.group(1), int(m.group(2))
    out['pac_url'] = sysutil.kread('kioslaverc', 'Proxy Settings', 'Proxy Config Script', '')
    out['no_proxy'] = sysutil.kread('kioslaverc', 'Proxy Settings', 'NoProxyFor', '')
    return out


def proxy_set(mode, http_host='', http_port=0, socks_host='', socks_port=0, pac_url='', no_proxy=''):
    if mode not in PROXY_MODES:
        raise ValueError('Proxy mode must be none, manual or auto.')
    if mode == 'manual':
        if not (http_host or socks_host):
            raise ValueError('Enter a proxy host.')
        for host, port in ((http_host, http_port), (socks_host, socks_port)):
            if host and (not _host_ok(host) or not 1 <= int(port) <= 65535):
                raise ValueError('Enter a valid proxy host and port (1 to 65535).')
    if mode == 'auto' and not re.fullmatch(r'(https?|file)://\S{1,500}', pac_url or ''):
        raise ValueError('Enter the address of the proxy script (http:// or https://).')
    if not re.fullmatch(r'[A-Za-z0-9.,:*/_\-\[\] ]{0,500}', no_proxy or ''):
        raise ValueError('The exceptions list may only hold host names, addresses and commas.')
    sysutil.gsettings_set('org.gnome.system.proxy', 'mode', f"'{mode}'")
    sysutil.kwrite('kioslaverc', 'Proxy Settings', 'ProxyType', _KDE_TYPE[mode])
    if mode == 'manual':
        if http_host:
            sysutil.gsettings_set('org.gnome.system.proxy.http', 'host', f"'{http_host}'")
            sysutil.gsettings_set('org.gnome.system.proxy.http', 'port', int(http_port))
            sysutil.kwrite('kioslaverc', 'Proxy Settings', 'httpProxy', f'http://{http_host}:{int(http_port)}')
            sysutil.kwrite('kioslaverc', 'Proxy Settings', 'httpsProxy', f'http://{http_host}:{int(http_port)}')
        if socks_host:
            sysutil.gsettings_set('org.gnome.system.proxy.socks', 'host', f"'{socks_host}'")
            sysutil.gsettings_set('org.gnome.system.proxy.socks', 'port', int(socks_port))
            sysutil.kwrite('kioslaverc', 'Proxy Settings', 'socksProxy', f'socks://{socks_host}:{int(socks_port)}')
        sysutil.kwrite('kioslaverc', 'Proxy Settings', 'NoProxyFor', no_proxy)
    if mode == 'auto':
        sysutil.gsettings_set('org.gnome.system.proxy', 'autoconfig-url', f"'{pac_url}'")
        sysutil.kwrite('kioslaverc', 'Proxy Settings', 'Proxy Config Script', pac_url)
    return proxy_get()


# ---------------------------------------------------------------- DNS
DNS_PRESETS = [('auto', 'Automatic (from the network)', []), ('cloudflare', 'Cloudflare 1.1.1.1', ['1.1.1.1', '1.0.0.1']),
               ('quad9', 'Quad9 9.9.9.9', ['9.9.9.9', '149.112.112.112']), ('google', 'Google 8.8.8.8', ['8.8.8.8', '8.8.4.4'])]


def check_dns(servers):
    out = []
    for s in servers:
        try:
            out.append(str(ipaddress.ip_address(s.strip())))
        except ValueError:
            raise ValueError(f'"{s}" is not a valid IP address.') from None
    if len(out) > 4:
        raise ValueError('Use at most four DNS servers.')
    return out


def dns_get(uuid):
    res = sysutil.run(['nmcli', '-t', '-f', 'ipv4.dns,ipv4.ignore-auto-dns,ipv6.dns', 'connection', 'show', 'uuid', _check_uuid(uuid)])
    info = {}
    for line in res.out.splitlines():
        f = sysutil.split_nmcli(line)
        info[f[0]] = f[1] if len(f) > 1 else ''
    servers = [s for s in re.split(r'[ ,]+', info.get('ipv4.dns', '')) if s]
    return {'servers': servers, 'automatic': info.get('ipv4.ignore-auto-dns', 'no') != 'yes' or not servers}


def dns_set(uuid, servers):
    """Set custom DNS servers on a profile (empty list = automatic) and re-activate it if it is up."""
    servers = check_dns(servers)
    uuid = _check_uuid(uuid)
    argv = ['nmcli', 'connection', 'modify', 'uuid', uuid, 'ipv4.dns', ' '.join(servers), 'ipv4.ignore-auto-dns', 'yes' if servers else 'no']
    if sysutil.run(argv).code != 0:
        return {'ok': False, 'error': 'NetworkManager refused the change.'}
    active = next((c for c in connections() if c['uuid'] == uuid and c['active']), None)
    if active:
        sysutil.run(['nmcli', 'connection', 'up', 'uuid', uuid], timeout=30)
    return {'ok': True, 'error': None}
