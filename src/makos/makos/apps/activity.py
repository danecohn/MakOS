"""Activity: processes, CPU, memory, GPU, network and energy from /proc and /sys (read-only)."""
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .. import ui
from .base import AppWindow, confirm, human

CLK = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100


@dataclass
class Proc:
    pid: int
    name: str
    uid: int
    state: str
    rss: int
    threads: int
    ticks: int
    start: int
    cpu: float = 0.0


def read_proc(pid, root='/proc'):
    base = Path(root) / str(pid)
    try:
        stat = (base / 'stat').read_text()
        # comm may contain spaces and parentheses: split on the last ')'
        head, tail = stat.rsplit(')', 1)
        name = head.split('(', 1)[1]
        f = tail.split()
        status = (base / 'status').read_text()
        uid = next(int(l.split()[1]) for l in status.splitlines() if l.startswith('Uid:'))
        page = os.sysconf('SC_PAGE_SIZE') if hasattr(os, 'sysconf') else 4096
        return Proc(int(pid), name, uid, f[0], int(f[21]) * page, int(f[17]), int(f[11]) + int(f[12]), int(f[19]))
    except (OSError, ValueError, IndexError, StopIteration):
        return None


class Sampler:
    """Process CPU% is a delta between two samples, so the first sample reports 0."""

    def __init__(self, root='/proc'):
        self.root, self.prev, self.when = root, {}, 0.0
        self.cpu_prev = None
        self.net_prev = None

    def processes(self):
        now = time.monotonic()
        elapsed = max(now - self.when, 1e-3) if self.when else None
        out, seen = [], {}
        for entry in os.listdir(self.root):
            if not entry.isdigit():
                continue
            p = read_proc(entry, self.root)
            if not p:
                continue
            seen[p.pid] = (p.ticks, p.start)
            old = self.prev.get(p.pid)
            if elapsed and old and old[1] == p.start:
                p.cpu = max(0.0, (p.ticks - old[0]) / CLK / elapsed * 100)
            out.append(p)
        self.prev, self.when = seen, now
        return out

    def cpu(self):
        """Overall CPU busy percent since the last call and per-core list."""
        total, cores = None, []
        try:
            lines = [l for l in (Path(self.root) / 'stat').read_text().splitlines() if l.startswith('cpu')]
        except OSError:
            return 0.0, []
        current = {}
        for l in lines:
            parts = l.split()
            nums = [int(x) for x in parts[1:9]]
            current[parts[0]] = (sum(nums), nums[3] + nums[4])
        prev, self.cpu_prev = self.cpu_prev, current
        if not prev:
            return 0.0, []

        def pct(k):
            dt_, di = current[k][0] - prev.get(k, (0, 0))[0], current[k][1] - prev.get(k, (0, 0))[1]
            return max(0.0, min(100.0, (dt_ - di) / dt_ * 100)) if dt_ > 0 else 0.0
        return pct('cpu'), [pct(k) for k in sorted((k for k in current if k != 'cpu'), key=lambda x: int(x[3:]))]

    def network(self):
        """(rx_bytes_per_s, tx_bytes_per_s) summed over non-loopback interfaces."""
        rx = tx = 0
        try:
            for line in (Path(self.root) / 'net/dev').read_text().splitlines()[2:]:
                name, data = line.split(':', 1)
                if name.strip() == 'lo':
                    continue
                f = data.split()
                rx += int(f[0])
                tx += int(f[8])
        except (OSError, ValueError, IndexError):
            return 0, 0
        now = time.monotonic()
        prev, self.net_prev = self.net_prev, (now, rx, tx)
        if not prev or now <= prev[0]:
            return 0, 0
        return max(0, (rx - prev[1]) / (now - prev[0])), max(0, (tx - prev[2]) / (now - prev[0]))


def memory(root='/proc'):
    info = {}
    try:
        for l in (Path(root) / 'meminfo').read_text().splitlines():
            k, v = l.split(':', 1)
            info[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        return {'total': 0, 'used': 0, 'swap_total': 0, 'swap_used': 0}
    total = info.get('MemTotal', 0)
    return {'total': total, 'used': total - info.get('MemAvailable', 0), 'swap_total': info.get('SwapTotal', 0), 'swap_used': info.get('SwapTotal', 0) - info.get('SwapFree', 0)}


def gpu(sys_root='/sys'):
    """Busy percent when the driver exports it (amdgpu); otherwise the devfreq clock as a proxy; else None."""
    base = Path(sys_root)
    for p in sorted(base.glob('class/drm/card*/device/gpu_busy_percent')):
        try:
            return {'percent': float(p.read_text()), 'kind': 'busy', 'name': p.parent.name}
        except (OSError, ValueError):
            pass
    for d in sorted(base.glob('class/devfreq/*')):
        if any(t in d.name.lower() for t in ('gpu', 'kgsl', 'adreno', 'mali', 'panfrost')):
            try:
                cur, top = int((d / 'cur_freq').read_text()), int((d / 'max_freq').read_text())
                return {'percent': 100.0 * cur / top if top else 0.0, 'kind': 'clock', 'name': d.name}
            except (OSError, ValueError):
                pass
    return None


def energy(sys_root='/sys'):
    base = Path(sys_root) / 'class/power_supply'
    out = {'battery': None, 'watts': None, 'status': '', 'temp_c': None}
    for d in sorted(base.glob('*')) if base.exists() else []:
        try:
            if (d / 'type').read_text().strip() != 'Battery':
                continue
            out['battery'] = int((d / 'capacity').read_text())
            out['status'] = (d / 'status').read_text().strip()
            if (d / 'power_now').exists():
                out['watts'] = int((d / 'power_now').read_text()) / 1e6
            elif (d / 'current_now').exists() and (d / 'voltage_now').exists():
                out['watts'] = abs(int((d / 'current_now').read_text())) * int((d / 'voltage_now').read_text()) / 1e12
            break
        except (OSError, ValueError):
            continue
    temps = []
    for z in Path(sys_root).glob('class/thermal/thermal_zone*/temp'):
        try:
            temps.append(int(z.read_text()) / 1000)
        except (OSError, ValueError):
            pass
    out['temp_c'] = max(temps) if temps else None
    return out


def can_signal(proc, my_uid=None, my_pid=None):
    """Only the user's own, non-system processes; never PID 1 or this app."""
    return proc.uid == (os.getuid() if my_uid is None else my_uid) and proc.pid not in (0, 1, os.getpid() if my_pid is None else my_pid)


def send_signal(pid, start, sig, root='/proc'):
    """Signals pid only if it is still the same process (guards against PID reuse). Returns True when sent."""
    p = read_proc(pid, root)
    if not p or p.start != start or not can_signal(p):
        return False
    os.kill(pid, sig)
    return True


MENU = [('File', [('Quit Process…', 'quit_proc', '<Primary>k'), ('Force Quit Process…', 'force_proc', '<Primary><Shift>k'), None, ('Close', 'close', '<Primary>w')]),
        ('View', [('Sort by CPU', 'sort_cpu', None), ('Sort by Memory', 'sort_mem', None), ('Sort by Name', 'sort_name', None), None, ('Refresh Now', 'refresh', '<Primary>r')])]


class Graph(Gtk.DrawingArea):
    def __init__(self, title, maximum=100.0, unit='%'):
        super().__init__(content_height=70, hexpand=True)
        self.title, self.maximum, self.unit, self.values = title, maximum, unit, []
        self.set_draw_func(self.draw)

    def push(self, value):
        self.values = (self.values + [value])[-90:]
        if max(self.values, default=0) > self.maximum:
            self.maximum = max(self.values) * 1.2
        self.queue_draw()

    def draw(self, _a, cr, w, h):
        cr.set_source_rgb(.93, .95, .97)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgba(.4, .5, .6, .25)
        for i in range(1, 4):
            cr.move_to(0, h * i / 4)
            cr.line_to(w, h * i / 4)
        cr.stroke()
        if len(self.values) > 1:
            step = w / 89
            cr.move_to(w - step * (len(self.values) - 1), h)
            for i, v in enumerate(self.values):
                cr.line_to(w - step * (len(self.values) - 1 - i), h - h * min(v / self.maximum, 1))
            cr.line_to(w, h)
            cr.close_path()
            cr.set_source_rgba(.25, .55, .9, .45)
            cr.fill_preserve()
            cr.set_source_rgb(.15, .4, .75)
            cr.stroke()
        cr.set_source_rgb(.2, .25, .32)
        cr.move_to(8, 14)
        last = self.values[-1] if self.values else 0
        cr.show_text(f'{self.title}   {last:.0f}{self.unit}')


class Activity:
    def __init__(self, app, proc_root='/proc'):
        self.sampler = Sampler(proc_root)
        self.sort, self.selected, self.procs = 'cpu', None, []
        self.aw = AppWindow(app, 'Activity', 860, 620, MENU)
        self.win = self.aw.win
        for name, fn in (('quit_proc', lambda: self.ask(signal.SIGTERM)), ('force_proc', lambda: self.ask(signal.SIGKILL)), ('close', self.win.close),
                         ('sort_cpu', lambda: self.set_sort('cpu')), ('sort_mem', lambda: self.set_sort('mem')), ('sort_name', lambda: self.set_sort('name')), ('refresh', self.refresh)):
            self.aw.action(name, fn)
        self.stack = Gtk.Stack(vexpand=True)
        switch = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER)
        bar = ui.box(spacing=8, css='metal-toolbar')
        self.search = Gtk.SearchEntry(placeholder_text='Filter processes', hexpand=True)
        self.search.connect('search-changed', lambda *_: self.fill())
        bar.append(switch)
        bar.append(self.search)
        bar.append(ui.button('Quit Process', lambda: self.ask(signal.SIGTERM)))
        bar.append(ui.button('Force Quit', lambda: self.ask(signal.SIGKILL)))
        self.list = Gtk.ListBox()
        self.list.connect('row-selected', lambda _b, row: setattr(self, 'selected', row.proc if row else None))
        header = ui.box(spacing=6)
        for text, w, key in (('Process', 260, 'name'), ('PID', 70, None), ('User', 60, None), ('CPU %', 70, 'cpu'), ('Memory', 90, 'mem'), ('Threads', 60, None)):
            b = Gtk.Button(label=text, css_classes=['flat'])
            b.set_size_request(w, -1)
            if key:
                b.connect('clicked', lambda _b, k=key: self.set_sort(k))
            header.append(b)
        procs = ui.box(True)
        procs.append(header)
        procs.append(ui.scroll(self.list))
        self.stack.add_titled(procs, 'procs', 'Processes')
        perf = ui.box(True, 8, 'sheet')
        self.g_cpu, self.g_mem = Graph('CPU'), Graph('Memory')
        self.g_net, self.g_gpu, self.g_energy = Graph('Network', 100000, ' KB/s'), Graph('GPU'), Graph('Power', 15, ' W')
        self.notes = Gtk.Label(label='', xalign=0, css_classes=['hint'], wrap=True)
        for w in (self.g_cpu, self.g_mem, self.g_net, self.g_gpu, self.g_energy, self.notes):
            perf.append(w)
        self.stack.add_titled(ui.scroll(perf), 'perf', 'Performance')
        self.aw.body.append(bar)
        self.aw.body.append(self.stack)
        self.timer = GLib.timeout_add_seconds(2, self.tick)
        self.win.connect('close-request', lambda *_: (GLib.source_remove(self.timer) if self.timer else None, setattr(self, 'timer', 0), False)[2])
        self.sampler.processes()
        self.sampler.cpu()
        self.sampler.network()
        GLib.timeout_add(700, self.tick_once)

    def tick_once(self):
        self.refresh()
        return False

    def tick(self):
        if not self.win.get_visible():
            return False
        self.refresh()
        return True

    def set_sort(self, key):
        self.sort = key
        self.fill()

    def refresh(self):
        self.procs = self.sampler.processes()
        cpu, cores = self.sampler.cpu()
        mem = memory()
        rx, tx = self.sampler.network()
        self.g_cpu.push(cpu)
        self.g_mem.push(100 * mem['used'] / mem['total'] if mem['total'] else 0)
        self.g_net.push((rx + tx) / 1000)
        g, e = gpu(), energy()
        if g:
            self.g_gpu.title = 'GPU ' + ('busy' if g['kind'] == 'busy' else 'clock (proxy)')
            self.g_gpu.push(g['percent'])
        if e['watts'] is not None:
            self.g_energy.push(e['watts'])
        self.notes.set_text(f"{len(cores)} cores   memory {human(mem['used'])} of {human(mem['total'])}   swap {human(mem['swap_used'])} of {human(mem['swap_total'])}   "
                            f"network ↓{human(rx)}/s ↑{human(tx)}/s   " + ('GPU: ' + g['name'] + (' load' if g['kind'] == 'busy' else ' clock relative to maximum, not true load') if g else 'GPU: no load counter exported by this driver')
                            + (f"   battery {e['battery']}% {e['status']}" if e['battery'] is not None else '') + (f"   {e['watts']:.1f} W" if e['watts'] is not None else '')
                            + (f"   hottest sensor {e['temp_c']:.0f} °C" if e['temp_c'] is not None else ''))
        self.fill()
        self.aw.say(f'{len(self.procs)} processes   CPU {cpu:.0f}%   memory {human(mem["used"])} used')

    def fill(self):
        q = self.search.get_text().casefold()
        key = {'cpu': lambda p: -p.cpu, 'mem': lambda p: -p.rss, 'name': lambda p: p.name.casefold()}[self.sort]
        rows = sorted((p for p in self.procs if q in p.name.casefold() or q == str(p.pid)), key=key)[:150]
        ui.clear(self.list)
        keep = self.selected.pid if self.selected else None
        select = None
        for p in rows:
            row = Gtk.ListBoxRow()
            row.proc = p
            line = ui.box(spacing=6)
            for text, width in ((p.name, 260), (str(p.pid), 70), ('me' if p.uid == os.getuid() else ('root' if p.uid == 0 else str(p.uid)), 60), (f'{p.cpu:.1f}', 70), (human(p.rss), 90), (str(p.threads), 60)):
                line.append(Gtk.Label(label=text, xalign=0, width_request=width, ellipsize=3))
            row.set_child(line)
            self.list.append(row)
            if p.pid == keep:
                select = row
        if select:
            self.list.select_row(select)

    def ask(self, sig):
        p = self.selected
        if not p:
            self.aw.say('Select a process first.')
            return
        if not can_signal(p):
            ui.message(self.win.get_application(), 'Not allowed', 'Activity only ends processes that belong to you.')
            return
        force = sig == signal.SIGKILL
        confirm(self.win, ('Force quit ' if force else 'Quit ') + f'"{p.name}" (PID {p.pid})?',
                'Unsaved work in this program will be lost.' if force else 'The program is asked to quit and may save its work first.',
                'Force Quit' if force else 'Quit', 'Cancel', lambda: self.aw.say('Signal sent.' if send_signal(p.pid, p.start, sig) else 'That process has already changed or ended.'), destructive=True)


def open_window(app, path=None):
    a = Activity(app)
    a.aw.present()
    return a
