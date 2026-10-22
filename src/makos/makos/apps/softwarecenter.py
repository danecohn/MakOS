"""Software Center: search, install, remove and update apt packages (privileged via pkexec) and per-user Flatpaks.

apt changes always go through pkexec -> /usr/libexec/makos/makos-software-helper (polkit action
org.makos.software.manage, fixed allowlist). Flatpak changes use the user installation and need no
privileges. Nothing here runs apt directly. Not every package is an "app": results are packages.
"""
import os
import re
import shutil
import subprocess
import threading
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .. import ui
from .base import AppWindow, confirm

HELPER = os.environ.get('MAKOS_SOFTWARE_HELPER', '/usr/libexec/makos/makos-software-helper')
NAME = re.compile(r'^[a-z0-9][a-z0-9+.-]{1,99}$')
FLATPAK_ID = re.compile(r'^[A-Za-z0-9_]+(\.[A-Za-z0-9_-]+){2,}$')
UPGRADABLE = re.compile(r'^(?P<name>[^/\s]+)/(?P<suite>\S+)\s+(?P<new>\S+)\s+(?P<arch>\S+)(?:\s+\[upgradable from: (?P<old>[^\]]+)\])?')
ENV = {'LANG': 'C', 'LC_ALL': 'C', 'PATH': os.environ.get('PATH', '/usr/bin:/bin')}


def run(argv, timeout=30):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=ENV)
        return out.returncode, out.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ''


def parse_search(text, limit=100):
    rows = []
    for line in text.splitlines():
        if ' - ' in line:
            name, desc = line.split(' - ', 1)
            if NAME.match(name):
                rows.append((name, desc.strip()))
    return rows[:limit]


def parse_installed(text):
    """dpkg-query -W -f '${Package}\\t${db:Status-Abbrev}\\n' -> set of installed names."""
    out = set()
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) == 2 and parts[1].strip().startswith('ii'):
            out.add(parts[0].split(':')[0])
    return out


def parse_upgradable(text):
    rows = []
    for line in text.splitlines():
        m = UPGRADABLE.match(line)
        if m:
            rows.append({'name': m['name'], 'new': m['new'], 'old': m['old'] or '', 'security': 'security' in m['suite']})
    return rows


def parse_flatpak(text):
    rows = []
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) >= 2 and FLATPAK_ID.match(parts[0].strip()):
            rows.append((parts[0].strip(), parts[1].strip() + (' - ' + parts[2].strip() if len(parts) > 2 and parts[2].strip() else '')))
    return rows


def parse_progress(line):
    """APT::Status-Fd lines: 'pmstatus:pkg:45.2:Installing pkg' / 'dlstatus:1:12.5:Downloading'. -> (fraction, text) or None."""
    parts = line.strip().split(':', 3)
    if len(parts) == 4 and parts[0] in ('pmstatus', 'dlstatus'):
        try:
            return min(1.0, max(0.0, float(parts[2]) / 100)), parts[3]
        except ValueError:
            return None
    return None


def helper_argv(action, packages=(), helper=None):
    if action not in ('update', 'upgrade', 'install', 'remove'):
        raise ValueError('Unknown action')
    if action in ('install', 'remove'):
        if not packages or not all(NAME.match(p) for p in packages):
            raise ValueError('Invalid package name')
    return ['pkexec', helper or HELPER, action, *packages]


def flatpak_argv(action, ref):
    if action not in ('install', 'uninstall') or not FLATPAK_ID.match(ref):
        raise ValueError('Invalid Flatpak application')
    return ['flatpak', '--user', action, '-y', '--noninteractive'] + (['flathub'] if action == 'install' else []) + [ref]


def capabilities(which=shutil.which, helper=None):
    helper = helper or HELPER
    return {'apt': bool(which('apt-cache')) and os.path.exists(helper) and bool(which('pkexec')), 'flatpak': bool(which('flatpak')),
            'apt_search': bool(which('apt-cache')), 'helper_missing': not os.path.exists(helper)}


MENU = [('File', [('Check for Updates', 'refresh', '<Primary>r'), None, ('Close', 'close', '<Primary>w')]),
        ('Edit', [('Search', 'find', '<Primary>f')])]


class SoftwareCenter:
    def __init__(self, app):
        self.caps = capabilities()
        self.installed, self.busy, self.rows = set(), False, []
        self.aw = AppWindow(app, 'Software Center', 860, 640, MENU)
        self.win = self.aw.win
        for name, fn in (('refresh', lambda: self.run_action('update')), ('close', self.win.close), ('find', lambda: self.search.grab_focus())):
            self.aw.action(name, fn)
        bar = ui.box(spacing=8, css='metal-toolbar')
        self.search = Gtk.SearchEntry(placeholder_text='Search packages', hexpand=True)
        self.search.connect('activate', lambda *_: self.do_search())
        self.source = Gtk.DropDown.new_from_strings(['System packages (apt)', 'Flatpak (your account)'])
        self.source.set_selected(0)
        bar.append(self.search)
        bar.append(self.source)
        bar.append(ui.button('Search', self.do_search, 'suggested-action'))
        bar.append(ui.button('Updates', self.show_updates))
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.progress = Gtk.ProgressBar()
        self.log = Gtk.Label(label='', xalign=0, ellipsize=3, css_classes=['hint'])
        self.notice = Gtk.Label(label=self.honesty(), xalign=0, wrap=True, css_classes=['hint'])
        self.aw.body.append(bar)
        self.aw.body.append(self.notice)
        self.aw.body.append(ui.scroll(self.list))
        foot = ui.box(True, 3, 'statusbar')
        foot.append(self.progress)
        foot.append(self.log)
        self.aw.body.append(foot)
        self.load_installed()

    def honesty(self):
        c, notes = self.caps, []
        if not c['apt_search']:
            notes.append('apt-cache is not available: system package search is disabled.')
        elif c['helper_missing']:
            notes.append('The privileged helper is not installed, so installing or removing system packages is disabled (search still works).')
        elif not c['apt']:
            notes.append('pkexec is not installed: system changes are disabled.')
        if not c['flatpak']:
            notes.append('Flatpak is not installed: only system packages are available.')
        return ' '.join(notes) or 'System changes ask for your password through the system authentication dialog. Flatpak apps install for your account only.'

    def load_installed(self):
        def work():
            _c, out = run(['dpkg-query', '-W', '-f', '${Package}\t${db:Status-Abbrev}\n'], 20)
            GLib.idle_add(lambda: (setattr(self, 'installed', parse_installed(out)), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def show_rows(self, rows, flatpak=False, upgrade=False):
        ui.clear(self.list)
        for name, desc in rows:
            row = Gtk.ListBoxRow(activatable=False)
            line = ui.box(spacing=10)
            line.set_margin_top(4)
            line.set_margin_bottom(4)
            line.set_margin_start(10)
            line.set_margin_end(10)
            col = ui.box(True, 1)
            col.set_hexpand(True)
            col.append(Gtk.Label(label='Software updates' if name == '__all__' else name, xalign=0, css_classes=['title-label']))
            col.append(Gtk.Label(label=desc, xalign=0, ellipsize=3, css_classes=['hint']))
            line.append(col)
            installed = name in self.installed and not flatpak
            if upgrade:
                label, act = 'Update All', None
            else:
                label, act = ('Remove', 'remove') if installed else ('Install', 'install')
            can = (self.caps['flatpak'] if flatpak else self.caps['apt'])
            if upgrade and name != '__all__':
                line.append(Gtk.Label(label='available', css_classes=['hint']))
            else:
                b = ui.button(label, lambda n=name, a=act, f=flatpak, u=upgrade: self.act(n, a, f, u), 'suggested-action' if act == 'install' or upgrade else None)
                b.set_sensitive(can and not self.busy)
                line.append(b)
            row.set_child(line)
            self.list.append(row)
        if not rows:
            self.list.append(Gtk.Label(label='Nothing found.', css_classes=['hint'], margin_top=30))
        self.aw.say(f'{len(rows)} results')

    def do_search(self):
        q = self.search.get_text().strip()
        if len(q) < 2:
            return
        flat = self.source.get_selected() == 1
        self.aw.say('Searching…')

        def work():
            if flat:
                _c, out = run(['flatpak', '--user', 'search', '--columns=application,name,description', q], 40) if self.caps['flatpak'] else (127, '')
                rows = parse_flatpak(out)
            else:
                _c, out = run(['apt-cache', 'search', '--', q]) if self.caps['apt_search'] else (127, '')
                rows = parse_search(out)
            GLib.idle_add(lambda: (self.show_rows(rows, flat), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def show_updates(self):
        def work():
            _c, out = run(['apt', 'list', '--upgradable'], 30)
            rows = parse_upgradable(out)
            GLib.idle_add(lambda: (self.show_rows([('__all__', f'{len(rows)} package updates available' + (' (including security)' if any(r['security'] for r in rows) else ''))] + [(r['name'], f"{r['old']} → {r['new']}") for r in rows], upgrade=True), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def act(self, name, action, flatpak, upgrade):
        if upgrade:
            return self.run_action('upgrade')
        if action == 'remove':
            return confirm(self.win, f'Remove {name}?', 'The package and its configuration stay on disk where apt keeps them; other software that needs it may be removed too.', 'Remove', 'Cancel',
                           lambda: self.run_action('remove', [name], flatpak), destructive=True)
        self.run_action(action, [name], flatpak)

    def run_action(self, action, packages=(), flatpak=False):
        if self.busy:
            return
        try:
            argv = flatpak_argv('install' if action == 'install' else 'uninstall', packages[0]) if flatpak else helper_argv(action, packages)
        except ValueError as error:
            self.aw.say(str(error))
            return
        if not (self.caps['flatpak'] if flatpak else self.caps['apt']):
            self.aw.say('This action is not available on this system (see the note above).')
            return
        self.busy = True
        self.progress.set_fraction(0)
        self.log.set_text('Waiting for authentication…' if not flatpak else 'Working…')

        def work():
            try:
                proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, 'LANG': 'C'})
                for line in proc.stdout:
                    p = parse_progress(line)
                    GLib.idle_add(lambda p=p, line=line: self.progress_update(p, line))
                code = proc.wait()
            except OSError as error:
                code = 127
                GLib.idle_add(lambda: self.log.set_text(str(error)))
            GLib.idle_add(lambda: self.finished(code, action))
        threading.Thread(target=work, daemon=True).start()

    def progress_update(self, parsed, line):
        if parsed:
            self.progress.set_fraction(parsed[0])
            self.log.set_text(parsed[1])
        elif line.strip():
            self.progress.pulse()
            self.log.set_text(line.strip()[:200])
        return False

    def finished(self, code, action):
        self.busy = False
        self.progress.set_fraction(1.0 if code == 0 else 0)
        self.log.set_text(f'{action.title()} finished.' if code == 0 else f'{action.title()} did not complete (exit code {code}). Authentication may have been cancelled.')
        self.load_installed()
        return False


def open_window(app, path=None):
    s = SoftwareCenter(app)
    s.aw.present()
    return s
