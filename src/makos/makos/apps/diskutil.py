"""Disk Utility: devices, partitions, usage and SMART (read-only); mount/unmount only through udisks2."""
import json
import re
import subprocess
import threading
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib
from .. import ui
from .base import AppWindow, human, confirm

DEVICE_RE = re.compile(r'^/dev/[A-Za-z0-9_/-]{1,40}$')
SYSTEM_MOUNTS = ('/', '/boot', '/boot/efi', '/home', '/usr', '/var', '/etc', '/opt', '/snap')
COLUMNS = 'NAME,KNAME,PATH,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS,MODEL,RM,RO,PKNAME,FSUSED,FSAVAIL,UUID'


def parse_lsblk(text):
    """Flatten lsblk -J output into rows; loop/ram devices (snaps) are dropped."""
    rows = []
    try:
        data = json.loads(text)
    except ValueError:
        return rows

    def walk(nodes, depth):
        for n in nodes:
            if n.get('type') in ('loop', 'rom') and depth == 0 and not (n.get('mountpoints') or [None])[0]:
                continue
            if n.get('type') == 'loop':
                continue
            mounts = [m for m in (n.get('mountpoints') or []) if m]
            rows.append({'path': n.get('path') or '/dev/' + n.get('name', ''), 'name': n.get('name', ''), 'type': n.get('type', ''), 'size': int(n.get('size') or 0),
                         'fstype': n.get('fstype') or '', 'label': n.get('label') or '', 'mounts': mounts, 'model': (n.get('model') or '').strip(),
                         'removable': bool(n.get('rm')), 'readonly': bool(n.get('ro')), 'parent': n.get('pkname') or '', 'used': n.get('fsused'), 'free': n.get('fsavail'),
                         'depth': depth, 'uuid': n.get('uuid') or ''})
            walk(n.get('children') or [], depth + 1)
    walk(data.get('blockdevices') or [], 0)
    return rows


def lsblk():
    try:
        out = subprocess.run(['lsblk', '-J', '-b', '-o', COLUMNS], capture_output=True, text=True, timeout=8)
        return parse_lsblk(out.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return []


def can_unmount(row):
    """Only real mount points, never the running system's own."""
    mounts = [m for m in row['mounts'] if m.startswith('/')]
    return bool(mounts) and not any(m in SYSTEM_MOUNTS or m.startswith('/snap/') for m in mounts)


def can_mount(row):
    return bool(row['fstype']) and not row['mounts'] and row['type'] in ('part', 'disk') and row['fstype'] not in ('swap', 'crypto_LUKS', 'LVM2_member')


def udisks_command(action, row, known_paths):
    """argv for udisksctl. Refuses unknown or malformed device paths and system mounts."""
    path = row['path']
    if action not in ('mount', 'unmount') or not DEVICE_RE.match(path) or path not in known_paths:
        raise ValueError('Unknown device')
    if action == 'mount' and not can_mount(row):
        raise ValueError('This volume cannot be mounted here')
    if action == 'unmount' and not can_unmount(row):
        raise ValueError('System volumes cannot be unmounted from here')
    return ['udisksctl', action, '-b', path]


def smart_from_objects(objects):
    """{device path: summary} from the udisks GetManagedObjects mapping (already unpacked to python)."""
    drives, out = {}, {}
    for opath, ifaces in objects.items():
        if 'org.freedesktop.UDisks2.Drive' in ifaces:
            info = {'model': ifaces['org.freedesktop.UDisks2.Drive'].get('Model', ''), 'smart': None}
            ata, nvme = ifaces.get('org.freedesktop.UDisks2.Drive.Ata'), ifaces.get('org.freedesktop.UDisks2.NVMe.Controller')
            if ata and ata.get('SmartSupported'):
                info['smart'] = {'passed': not ata.get('SmartFailing', False), 'temperature_c': round(ata.get('SmartTemperature', 0) - 273.15, 1) or None,
                                 'power_on_hours': int(ata.get('SmartPowerOnSeconds', 0)) // 3600, 'enabled': bool(ata.get('SmartEnabled')), 'bus': 'ATA'}
            elif nvme:
                info['smart'] = {'passed': not nvme.get('SmartCriticalWarning'), 'temperature_c': round(nvme.get('SmartTemperature', 0) - 273.15, 1) or None,
                                 'power_on_hours': int(nvme.get('SmartPowerOnHours', 0)), 'enabled': True, 'bus': 'NVMe'}
            drives[opath] = info
    for ifaces in objects.values():
        block = ifaces.get('org.freedesktop.UDisks2.Block')
        if block and block.get('Drive', '/') in drives:
            dev = bytes(block.get('Device', b'')).rstrip(b'\0').decode(errors='replace')
            out[dev] = drives[block['Drive']]
    return out


def read_smart():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        reply = bus.call_sync('org.freedesktop.UDisks2', '/org/freedesktop/UDisks2', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects', None, None, Gio.DBusCallFlags.NONE, 5000, None)
        return smart_from_objects(reply.unpack()[0])
    except GLib.Error:
        return None


MENU = [('File', [('Mount', 'mount', '<Primary>m'), ('Unmount', 'unmount', '<Primary>u'), None, ('Close', 'close', '<Primary>w')]),
        ('View', [('Refresh', 'refresh', '<Primary>r')])]


class DiskUtility:
    def __init__(self, app, rows=None, smart=None):
        self.rows, self.smart, self.current = rows or [], smart, None
        self.aw = AppWindow(app, 'Disk Utility', 900, 580, MENU)
        self.win = self.aw.win
        for name, fn in (('mount', lambda: self.do('mount')), ('unmount', lambda: self.do('unmount')), ('close', self.win.close), ('refresh', self.reload)):
            self.aw.action(name, fn)
        paned = Gtk.Paned(position=300, vexpand=True)
        self.list = Gtk.ListBox(css_classes=['app-sidebar'])
        self.list.connect('row-selected', self.pick)
        paned.set_start_child(ui.scroll(self.list))
        right = ui.box(True, 10, 'sheet')
        self.detail = Gtk.Label(label='', xalign=0, yalign=0, selectable=True, wrap=True, vexpand=True)
        self.usage = Gtk.LevelBar(min_value=0, max_value=100, css_classes=['meter'])
        buttons = ui.box(spacing=8)
        self.mount_b, self.unmount_b = ui.button('Mount', lambda: self.do('mount')), ui.button('Unmount', lambda: self.do('unmount'))
        buttons.append(self.mount_b)
        buttons.append(self.unmount_b)
        right.append(self.usage)
        right.append(self.detail)
        right.append(Gtk.Label(label='Disk Utility is read-only. It can mount and unmount volumes through udisks2, and cannot format, partition or erase.', wrap=True, xalign=0, css_classes=['hint']))
        right.append(buttons)
        paned.set_end_child(right)
        self.aw.body.append(paned)
        if rows is None:
            self.reload()
        else:
            self.fill()

    def reload(self):
        self.aw.say('Reading devices…')

        def work():
            rows, smart = lsblk(), read_smart()
            GLib.idle_add(lambda: (setattr(self, 'rows', rows), setattr(self, 'smart', smart), self.fill(), False)[3])
        threading.Thread(target=work, daemon=True).start()

    def fill(self):
        ui.clear(self.list)
        for r in self.rows:
            row = Gtk.ListBoxRow()
            row.data = r
            title = (r['label'] or r['model'] or r['name']) if r['depth'] == 0 or r['label'] else r['name']
            line = ui.box(spacing=6)
            line.set_margin_start(14 * r['depth'])
            line.append(ui.icon('disk-utility' if r['depth'] == 0 else 'folder', 24))
            col = ui.box(True)
            col.append(Gtk.Label(label=title, xalign=0, css_classes=['title-label']))
            col.append(Gtk.Label(label=f"{human(r['size'])}  {r['fstype'] or r['type']}", xalign=0, css_classes=['hint']))
            line.append(col)
            row.set_child(line)
            self.list.append(row)
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)
        self.aw.say(f'{len(self.rows)} devices and volumes')

    def pick(self, _b, row):
        self.current = row.data if row else None
        r = self.current
        if not r:
            self.detail.set_text('No device selected.')
            return
        lines = [f"Device: {r['path']}", f"Type: {r['type']}", f"Size: {human(r['size'])}"]
        for key, label in (('model', 'Model'), ('fstype', 'File system'), ('label', 'Name'), ('uuid', 'UUID')):
            if r[key]:
                lines.append(f'{label}: {r[key]}')
        lines.append('Removable: ' + ('yes' if r['removable'] else 'no') + '   Read-only: ' + ('yes' if r['readonly'] else 'no'))
        if r['mounts']:
            lines.append('Mounted at: ' + ', '.join(r['mounts']))
        pct = 0
        if r['used'] is not None and r['size']:
            fs_total = (r['used'] or 0) + (r['free'] or 0)
            pct = 100 * (r['used'] or 0) / fs_total if fs_total else 0
            lines.append(f"Used: {human(r['used'])}   Free: {human(r['free'])}   ({pct:.0f}% full)")
        self.usage.set_value(pct)
        info = None if self.smart is None else (self.smart.get(r['path']) or self.smart.get('/dev/' + r['parent']))
        if r['depth'] == 0 or info:
            if self.smart is None:
                lines.append('SMART: udisks2 is not reachable, so health data is unavailable.')
            elif info and info.get('smart'):
                s = info['smart']
                lines.append(f"SMART ({s['bus']}): {'passed' if s['passed'] else 'WARNING: the drive reports a failing status'}"
                             + (f", {s['temperature_c']} °C" if s['temperature_c'] else '') + f", {s['power_on_hours']} hours powered on")
            elif r['depth'] == 0:
                lines.append('SMART: not reported for this device (virtual disks and many USB bridges do not expose it).')
        self.detail.set_text('\n'.join(lines))
        self.mount_b.set_sensitive(can_mount(r))
        self.unmount_b.set_sensitive(can_unmount(r))
        self.aw.enable('mount', can_mount(r))
        self.aw.enable('unmount', can_unmount(r))

    def do(self, action):
        r = self.current
        if not r:
            return
        try:
            argv = udisks_command(action, r, {x['path'] for x in self.rows})
        except ValueError as error:
            ui.message(self.win.get_application(), 'Disk Utility', str(error))
            return

        def run():
            def work():
                try:
                    out = subprocess.run(argv, capture_output=True, text=True, timeout=90)
                    text = (out.stdout or out.stderr).strip() or 'Done.'
                except (OSError, subprocess.TimeoutExpired) as error:
                    text = str(error)
                GLib.idle_add(lambda: (self.aw.say(text), self.reload(), False)[2])
            threading.Thread(target=work, daemon=True).start()
        if action == 'unmount':
            confirm(self.win, f"Unmount {r['label'] or r['path']}?", 'Programs using files on this volume may lose access to them.', 'Unmount', 'Cancel', run)
        else:
            run()


def open_window(app, path=None):
    d = DiskUtility(app)
    d.aw.present()
    return d
