"""Bluetooth settings backend: BlueZ over the system D-Bus (via busctl), pairing through bluetoothctl's agent."""
import json
import re

from . import sysutil

BLUEZ = 'org.bluez'
MAC = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')

ICON_KIND = {'audio-headset': 'Headset', 'audio-headphones': 'Headphones', 'audio-card': 'Speaker', 'input-keyboard': 'Keyboard',
             'input-mouse': 'Mouse', 'input-gaming': 'Controller', 'input-tablet': 'Tablet', 'phone': 'Phone', 'computer': 'Computer',
             'camera-photo': 'Camera', 'printer': 'Printer'}


def _unwrap(v):
    """busctl -j wraps every value as {"type": ..., "data": ...}; flatten that into plain Python."""
    if isinstance(v, dict) and set(v) == {'type', 'data'}:
        return _unwrap(v['data'])
    if isinstance(v, dict):
        return {k: _unwrap(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_unwrap(x) for x in v]
    return v


def managed():
    """{object path: {interface: {property: value}}} for everything BlueZ exports, or {} when BlueZ is absent."""
    res = sysutil.run(['busctl', '--system', '-j', 'call', BLUEZ, '/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects'], timeout=8)
    if res.code != 0 or not res.out:
        return {}
    try:
        data = json.loads(res.out)['data'][0]
    except (ValueError, KeyError, IndexError):
        return {}
    return _unwrap(data)


def check_mac(mac):
    if not MAC.match(mac or ''):
        raise ValueError('Not a valid Bluetooth address.')
    return mac.upper()


def _dev_path(adapter_path, mac):
    return f"{adapter_path}/dev_{check_mac(mac).replace(':', '_')}"


def adapters():
    out = []
    for path, ifaces in sorted(managed().items()):
        a = ifaces.get('org.bluez.Adapter1')
        if a:
            out.append({'path': path, 'name': a.get('Alias') or a.get('Name') or path.rsplit('/', 1)[-1], 'address': a.get('Address', ''),
                        'powered': bool(a.get('Powered')), 'discoverable': bool(a.get('Discoverable')), 'discovering': bool(a.get('Discovering'))})
    return out


def adapter():
    found = adapters()
    return found[0] if found else None


def devices(include_unpaired=True):
    out = []
    for path, ifaces in managed().items():
        d = ifaces.get('org.bluez.Device1')
        if not d:
            continue
        paired = bool(d.get('Paired'))
        if not paired and not include_unpaired:
            continue
        bat = ifaces.get('org.bluez.Battery1', {}).get('Percentage')
        icon = d.get('Icon', '')
        out.append({'path': path, 'address': d.get('Address', ''), 'name': d.get('Alias') or d.get('Name') or d.get('Address', ''),
                    'kind': ICON_KIND.get(icon, 'Device'), 'icon': icon, 'paired': paired, 'trusted': bool(d.get('Trusted')),
                    'connected': bool(d.get('Connected')), 'battery': int(bat) if bat is not None else None, 'rssi': d.get('RSSI')})
    return sorted(out, key=lambda d: (not d['connected'], not d['paired'], d['name'].lower()))


def _set_prop(path, iface, prop, sig, value):
    return sysutil.run(['busctl', '--system', 'set-property', BLUEZ, path, iface, prop, sig, value], timeout=10).code == 0


def set_power(on):
    a = adapter()
    if not a:
        return False
    sysutil.run(['rfkill', 'unblock', 'bluetooth']) if on and sysutil.have('rfkill') else None
    return _set_prop(a['path'], 'org.bluez.Adapter1', 'Powered', 'b', 'true' if on else 'false')


def set_discoverable(on):
    a = adapter()
    return bool(a) and _set_prop(a['path'], 'org.bluez.Adapter1', 'Discoverable', 'b', 'true' if on else 'false')


def scan(on=True):
    a = adapter()
    if not a:
        return False
    return sysutil.run(['busctl', '--system', 'call', BLUEZ, a['path'], 'org.bluez.Adapter1', 'StartDiscovery' if on else 'StopDiscovery'], timeout=10).code == 0


def _device_call(mac, method, timeout=30):
    a = adapter()
    if not a:
        return {'ok': False, 'error': 'No Bluetooth adapter found.'}
    res = sysutil.run(['busctl', '--system', 'call', BLUEZ, _dev_path(a['path'], mac), 'org.bluez.Device1', method], timeout=timeout)
    return {'ok': res.code == 0, 'error': None if res.code == 0 else res.err[:300]}


def pair(mac):
    """Pair, trust and connect. bluetoothctl supplies the pairing agent (just-works pairing; keyboards that need a PIN are not supported here)."""
    check_mac(mac)
    res = sysutil.run(['bluetoothctl', '--agent', 'NoInputNoOutput', '--timeout', '40', 'pair', mac], timeout=50)
    if res.code != 0 or 'Failed' in res.out:
        return {'ok': False, 'error': (res.err or res.out.splitlines()[-1] if res.out else 'Pairing failed.')[:300]}
    trust(mac, True)
    return connect(mac)


def connect(mac):
    return _device_call(mac, 'Connect')


def disconnect(mac):
    return _device_call(mac, 'Disconnect')


def trust(mac, on=True):
    a = adapter()
    return bool(a) and _set_prop(_dev_path(a['path'], mac), 'org.bluez.Device1', 'Trusted', 'b', 'true' if on else 'false')


def forget(mac):
    a = adapter()
    if not a:
        return {'ok': False, 'error': 'No Bluetooth adapter found.'}
    res = sysutil.run(['busctl', '--system', 'call', BLUEZ, a['path'], 'org.bluez.Adapter1', 'RemoveDevice', 'o', _dev_path(a['path'], mac)], timeout=10)
    return {'ok': res.code == 0, 'error': None if res.code == 0 else res.err[:300]}


def rename(name):
    a = adapter()
    name = (name or '').strip()
    if not a or not re.fullmatch(r'[^\x00-\x1f]{1,60}', name):
        raise ValueError('Enter a name of up to 60 characters.')
    return _set_prop(a['path'], 'org.bluez.Adapter1', 'Alias', 's', name)
