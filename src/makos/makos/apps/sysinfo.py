"""System Information: hardware and software overview with a copyable report that carries no secrets."""
import os
import platform
import re
import subprocess
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
from .. import ui, common
from .base import AppWindow, human

VERSION = '0.1.0~dev6'
REDACTIONS = [
    (re.compile(r'\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b'), '<mac>'),
    (re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b'), '<ip>'),
    (re.compile(r'\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b'), '<ip6>'),
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '<email>'),
    (re.compile(r'(?i)\b(?:sk|pk|ghp|gho|xox[bap]|AKIA|eyJ)[\w-]{16,}'), '<secret>'),
    (re.compile(r'\b[0-9a-fA-F]{32,}\b'), '<id>'),
    (re.compile(r'(?i)(password|passwd|token|secret|api[_-]?key|serial(?: number)?)\s*[:=]\s*\S+'), r'\1: <hidden>'),
]


def redact(text, home=None, user=None):
    """Removes MAC/IP addresses, e-mail, key-like tokens, long ids, serials and the user's name/home path."""
    home = str(home or Path.home())
    user = user or os.environ.get('USER') or ''
    text = text.replace(home, '~')
    for pattern, repl in REDACTIONS:
        text = pattern.sub(repl, text)
    if user and len(user) > 2:
        text = re.sub(r'\b' + re.escape(user) + r'\b', '<user>', text)
    return text


def first_line(path, default=''):
    try:
        return Path(path).read_text(errors='replace').strip().splitlines()[0]
    except (OSError, IndexError):
        return default


def os_release(path='/etc/os-release'):
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                out[k] = v.strip('"')
    except OSError:
        pass
    return out


def cpu_info(root='/proc'):
    model, cores = '', 0
    try:
        text = (Path(root) / 'cpuinfo').read_text(errors='replace')
    except OSError:
        text = ''
    for l in text.splitlines():
        if l.lower().startswith(('model name', 'hardware')) and not model:
            model = l.split(':', 1)[1].strip()
        if l.startswith('processor'):
            cores += 1
    if not model:
        try:
            model = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=4).stdout
            m = re.search(r'Model name:\s*(.+)', model)
            model = m.group(1).strip() if m else platform.machine()
        except (OSError, subprocess.TimeoutExpired):
            model = platform.machine()
    return model, cores or os.cpu_count() or 0


def memory_total(root='/proc'):
    try:
        for l in (Path(root) / 'meminfo').read_text().splitlines():
            if l.startswith('MemTotal'):
                return int(l.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return 0


def gpu_names(sys_root='/sys'):
    names = []
    for d in sorted(Path(sys_root).glob('class/drm/card[0-9]/device')):
        driver = d / 'driver'
        label = os.path.basename(os.path.realpath(driver)) if driver.exists() else ''
        if label and label not in names:
            names.append(label)
    return names


def displays(sys_root='/sys'):
    out = []
    for p in sorted(Path(sys_root).glob('class/drm/card*-*/modes')):
        if (p.parent / 'status').exists() and first_line(p.parent / 'status') == 'connected':
            out.append(f"{p.parent.name.split('-', 1)[1]}: {first_line(p)}")
    return out


def tool_version(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=4).stdout.strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ''


def uptime(root='/proc'):
    try:
        return int(float(first_line(Path(root) / 'uptime').split()[0]))
    except (ValueError, IndexError):
        return 0


def gather():
    release = os_release()
    cpu, cores = cpu_info()
    seconds = uptime()
    sections = [
        ('Software', [('Operating system', f'Makk OS {VERSION} (development preview)'), ('Base', release.get('PRETTY_NAME', 'unknown')), ('Kernel', platform.release()),
                      ('Architecture', platform.machine()), ('Compositor', tool_version(['kwin_wayland', '--version']) or 'KWin (version unavailable)'),
                      ('Toolkit', 'GTK %s.%s.%s' % (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version())), ('Python', platform.python_version()),
                      ('Session', os.environ.get('XDG_CURRENT_DESKTOP', 'unknown') + ' / ' + os.environ.get('XDG_SESSION_TYPE', 'unknown'))]),
        ('Hardware', [('Model', first_line('/sys/class/dmi/id/product_name', first_line('/proc/device-tree/model', 'unknown')).replace('\x00', '')),
                      ('Processor', f'{cpu} ({cores} threads)'), ('Memory', human(memory_total())), ('Graphics driver', ', '.join(gpu_names()) or 'unknown'),
                      ('Displays', '; '.join(displays()) or 'unknown')]),
        ('Status', [('Uptime', f'{seconds // 3600} h {seconds % 3600 // 60} min')]),
    ]
    return sections


def report(sections=None, redact_secrets=True):
    sections = sections or gather()
    lines = ['Makk OS system report']
    for title, rows in sections:
        lines += ['', title]
        lines += [f'  {k}: {v}' for k, v in rows]
    text = '\n'.join(lines) + '\n'
    return redact(text) if redact_secrets else text


MENU = [('File', [('Copy Report', 'copy', '<Primary>c'), ('Refresh', 'refresh', '<Primary>r'), None, ('Close', 'close', '<Primary>w')])]


class SystemInfo:
    def __init__(self, app):
        self.aw = AppWindow(app, 'System Information', 560, 600, MENU)
        self.win = self.aw.win
        for name, fn in (('copy', self.copy), ('refresh', self.show), ('close', self.win.close)):
            self.aw.action(name, fn)
        col = ui.box(True, 10, 'sheet')
        head = ui.box(spacing=16)
        head.append(ui.icon('makos-logo', 72))
        titles = ui.box(True, 2)
        titles.append(Gtk.Label(label='Makk OS', xalign=0, css_classes=['hero']))
        titles.append(Gtk.Label(label='Developed by Cherry Blossom LLC', xalign=0))
        titles.append(Gtk.Label(label=f'Development preview {VERSION}', xalign=0, css_classes=['subtitle']))
        head.append(titles)
        col.append(head)
        self.text = Gtk.Label(xalign=0, yalign=0, selectable=True, wrap=True, vexpand=True)
        col.append(ui.scroll(self.text))
        row = ui.box(spacing=8)
        row.append(ui.button('Copy Report', self.copy, 'suggested-action'))
        row.append(Gtk.Label(label='The copied report omits addresses, serials, e-mail, user name and tokens.', css_classes=['hint']))
        col.append(row)
        self.aw.body.append(col)
        self.show()

    def show(self):
        self.text.set_text(report(redact_secrets=False).replace(str(Path.home()), '~'))
        self.aw.say('Hardware and software overview')

    def copy(self):
        Gdk.Display.get_default().get_clipboard().set(report())
        self.aw.say('Report copied (secrets removed).')


def open_window(app, path=None):
    s = SystemInfo(app)
    s.aw.present()
    return s
