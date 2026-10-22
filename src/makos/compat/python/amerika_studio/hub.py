"""Studio hub: four app tiles with status, Anthropic key setup, model, budget, New game, recent projects and the
"Allow local automation to use these tools" switch."""
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import __version__, agent_link, cli, common, keyring, keys, projects, ui
from .common import APP_LAUNCHERS, APP_TITLES, APPS, MODELS

BLURBS = {
    'render': ('Model in 3D by describing it. Blender underneath.', 'Powered by Blender'),
    'engine': ('Assemble a playable game from a recipe. Godot underneath.', 'Powered by Godot'),
    'sprite': ('Pixel art and animation with an AI sprite builder.', 'Original editor'),
    'box': ('Chiptune maker with an AI composer. A fork of BeepBox.', 'Based on BeepBox'),
}
BUDGETS = [('500 thousand', 500_000), ('1 million', 1_000_000), ('2 million', 2_000_000), ('5 million', 5_000_000),
           ('10 million', 10_000_000), ('Unlimited', 0)]
REFRESH_S = 3


def fmt(n):
    return f'{n:,}'


class Tile(Gtk.Box):
    def __init__(self, hub, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.hub, self.app = hub, app
        self.add_css_class('st-tile')
        self.set_hexpand(True)
        icon = Gtk.Image.new_from_icon_name(f'amerika-{app}')
        icon.set_pixel_size(96)
        icon.set_halign(Gtk.Align.CENTER)
        self.append(icon)
        name = ui.label(APP_TITLES[app], 'st-tile-name', xalign=0.5)
        self.append(name)
        blurb = ui.label(BLURBS[app][0], 'st-tile-sub', xalign=0.5, wrap=True)
        blurb.set_size_request(-1, 36)
        blurb.set_valign(Gtk.Align.START)
        self.append(blurb)
        self.append(ui.label(BLURBS[app][1].upper(), 'am-label', xalign=0.5))
        pills = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.p_installed = ui.label('', 'am-pill off')
        self.p_running = ui.label('', 'am-pill off')
        self.p_key = ui.label('', 'am-pill off')
        for p in (self.p_installed, self.p_running, self.p_key):
            pills.append(p)
        self.append(pills)
        self.open_btn = ui.button('Open', 'am-primary', lambda: hub.launch(app), halign=Gtk.Align.CENTER)
        self.append(self.open_btn)
        own = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.own = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.own.connect('state-set', self._own_set)
        own.append(self.own)
        self.own_label = ui.label('Own key', 'st-tile-sub')
        own.append(self.own_label)
        self.append(own)
        self._syncing = False

    def _own_set(self, _sw, state):
        if self._syncing:
            return False
        self.hub.set_override(self.app, state)
        return False

    def update(self, st):
        a = st['apps'][self.app]
        ui.set_pill(self.p_installed, 'INSTALLED' if a['installed'] else 'NOT INSTALLED', a['installed'])
        ui.set_pill(self.p_running, 'RUNNING' if a['running'] else 'STOPPED', a['running'])
        ui.set_pill(self.p_key, 'KEY SET' if st['keys'][self.app] else 'NO KEY', st['keys'][self.app])
        self.open_btn.set_sensitive(a['installed'])
        self.open_btn.set_label('Show' if a['running'] else 'Open')
        if a['installed']:
            self.remove_css_class('missing')
        else:
            self.add_css_class('missing')
        ov = st['overrides'][self.app]
        self._syncing = True
        self.own.set_active(bool(ov['override_stored'] and ov['override_enabled']))
        self._syncing = False
        self.own_label.set_label('Own key (saved)' if ov['override_stored'] else 'Own key')


class Hub(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title='Studio')
        self.add_css_class('st-window')
        self.set_default_size(1120, 820)
        self.paths = common.Paths()
        self.settings = common.load_settings(self.paths)
        self.status = None
        self._syncing = False
        self._busy = False
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self._hero())
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(body, f'set_margin_{m}')(24)
        tiles = Gtk.Box(spacing=16, homogeneous=True)
        self.tiles = {app: Tile(self, app) for app in APPS}
        for t in self.tiles.values():
            tiles.append(t)
        body.append(tiles)
        cols = Gtk.Box(spacing=16, homogeneous=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        left.append(self._key_card())
        left.append(self._model_card())
        right.append(self._game_card())
        right.append(self._agent_card())
        cols.append(left)
        cols.append(right)
        body.append(cols)
        body.append(self._footer())
        scroll.set_child(body)
        outer.append(scroll)
        self.set_child(outer)
        self.sync_controls()
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_S, self._tick)
        ui.in_thread(self._ensure_bridge)

    # ------------------------------------------------------------------ construction
    def _hero(self):
        hero = Gtk.Box(spacing=16)
        hero.add_css_class('st-hero')
        icon = Gtk.Image.new_from_icon_name('amerika-studio')
        icon.set_pixel_size(64)
        hero.append(icon)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        col.append(ui.label('STUDIO', 'st-brand'))
        col.append(ui.label('DESCRIBE IT. CLAUDE BUILDS IT.', 'st-tag'))
        hero.append(col)
        self.bridge_pill = ui.label('', 'am-pill off')
        self.bridge_pill.set_valign(Gtk.Align.CENTER)
        hero.append(self.bridge_pill)
        return hero

    def _key_card(self):
        self.key_state = ui.label('', 'am-keystate')
        self.key_btn = ui.button('Set up Anthropic key', 'am-primary', self.open_keys, halign=Gtk.Align.START)
        self.key_clear_btn = ui.button('Remove', 'am-secondary', self.clear_key, halign=Gtk.Align.START)
        row = Gtk.Box(spacing=8)
        row.append(self.key_btn)
        row.append(self.key_clear_btn)
        reuse = Gtk.Box(spacing=10)
        self.reuse_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.reuse_sw.connect('state-set', self._reuse_set)
        reuse.append(self.reuse_sw)
        self.reuse_label = ui.label("Legacy key reuse is disabled", None, wrap=True)
        reuse.append(self.reuse_label)
        reuse.set_visible(False)  # The retired Agent is not part of Studio.
        return ui.card(ui.label('ANTHROPIC KEY', 'am-label'),
                       ui.label('One key for all four apps. It lives in your login keyring; the apps talk to a local bridge '
                                'and never see it. Each tile can also use its own key.', 'am-sub', wrap=True),
                       self.key_state, row, reuse)

    def _model_card(self):
        self.model_dd = Gtk.DropDown.new_from_strings([m['name'] + '  -  ' + m['note'] for m in MODELS])
        self.model_dd.connect('notify::selected', self._model_changed)
        self.budget_dd = Gtk.DropDown.new_from_strings([b[0] for b in BUDGETS])
        self.budget_dd.connect('notify::selected', self._budget_changed)
        self.budget_bar = Gtk.LevelBar(min_value=0, max_value=1)
        self.budget_text = ui.label('', 'am-sub')
        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        grid.append(ui.label('MODEL', 'am-label'))
        grid.append(self.model_dd)
        grid.append(ui.label('DAILY TOKEN BUDGET', 'am-label'))
        grid.append(self.budget_dd)
        grid.append(self.budget_bar)
        grid.append(self.budget_text)
        return ui.card(grid)

    def _game_card(self):
        self.game_entry = Gtk.Entry(placeholder_text='Name your game', hexpand=True)
        self.game_entry.connect('activate', lambda *_: self.new_game())
        row = Gtk.Box(spacing=8)
        row.append(self.game_entry)
        row.append(ui.button('New game', 'am-primary', self.new_game))
        self.game_msg = ui.label('', 'am-sub', wrap=True)
        self.recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        return ui.card(ui.label('NEW GAME', 'am-label'),
                       ui.label('Creates ~/Studio/Render, Engine, Sprite and Box folders for it, plus a Godot starter.', 'am-sub', wrap=True),
                       row, self.game_msg, ui.label('RECENT', 'am-label'), self.recent_box)

    def _agent_card(self):
        row = Gtk.Box(spacing=10)
        self.agent_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.agent_sw.connect('state-set', self._agent_set)
        row.append(self.agent_sw)
        row.append(ui.label('Allow local automation to use these tools', None))
        self.agent_msg = ui.label('', 'am-sub', wrap=True)
        return ui.card(ui.label('LOCAL AUTOMATION', 'am-label'),
                       ui.label('Lets the local Studio bridge drive the four apps (render, engine, sprite and box tools). Anything that runs code '
                                'still asks you first, every time.', 'am-sub', wrap=True), row, self.agent_msg)

    def _footer(self):
        row = Gtk.Box(spacing=8)
        for text, doc in (('Studio guide', 'README.md'), ('Web shell contract', 'webview.md')):
            row.append(ui.button(text, 'st-link', lambda d=doc: self.open_doc(d)))
        row.append(ui.label(f'Studio {__version__}   |   Blender, Godot and BeepBox keep their own licences', 'am-sub'))
        return row

    # ------------------------------------------------------------------ state
    def _ensure_bridge(self):
        try:
            cli.ensure_bridge()
        except Exception:  # noqa: BLE001 - shown by the bridge pill
            pass

    def _tick(self):
        self.refresh()
        return True

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        ui.in_thread(lambda: cli.build_status(self.paths), self._on_status)

    def _on_status(self, st, err):
        self._busy = False
        if err or not st:
            return
        self.status = st
        self.settings = common.load_settings(self.paths)
        for t in self.tiles.values():
            t.update(st)
        ui.set_pill(self.bridge_pill, 'BRIDGE ONLINE' if st['bridge'] else 'BRIDGE OFFLINE', st['bridge'])
        has = st['shared_key']
        self.key_state.set_label('Key saved in your keyring' if has else 'No key saved yet')
        self.key_state.remove_css_class('saved')
        if has:
            self.key_state.add_css_class('saved')
        self.key_btn.set_label('Change key' if has else 'Set up Anthropic key')
        self.key_clear_btn.set_sensitive(has)
        self.reuse_label.set_label("Legacy key reuse is disabled" + (' (key found)' if st['agent_key_available'] else ' (no agent key found)'))
        self.reuse_sw.set_sensitive(st['agent_key_available'] or self.settings['reuse_agent_key'])
        b = st['budget']
        limit = b['daily_tokens']
        self.budget_bar.set_value(min(1.0, b['used_today'] / limit) if limit else 0)
        self.budget_text.set_label(f'{fmt(b["used_today"])} tokens used today' + (f' of {fmt(limit)}' if limit else ' (no limit)'))
        self.sync_controls()
        self.refresh_recent()

    def sync_controls(self):
        s = self.settings
        self._syncing = True
        self.model_dd.set_selected(next((i for i, m in enumerate(MODELS) if m['id'] == s['model']), 0))
        limit = s['daily_budget_tokens']
        self.budget_dd.set_selected(next((i for i, b in enumerate(BUDGETS) if b[1] == limit), 2))
        self.reuse_sw.set_active(s['reuse_agent_key'])
        self.agent_sw.set_active(s['agent_tools'])
        self._syncing = False

    def refresh_recent(self):
        ui.clear(self.recent_box)
        rows = projects.recent_projects(self.paths, 6)
        if not rows:
            self.recent_box.append(ui.label('Nothing yet. Create a game or open an app.', 'am-sub'))
        for r in rows:
            b = Gtk.Button(has_frame=False)
            b.add_css_class('st-row')
            line = Gtk.Box(spacing=10)
            line.append(ui.label(r['name'], 'am-appname'))
            line.get_first_child().set_hexpand(True)
            line.append(ui.label(APP_TITLES[r['app']].replace('Amerika', '').strip().upper(), 'am-label'))
            b.set_child(line)
            b.connect('clicked', lambda _b, p=r['path']: Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(p).get_uri(), None))
            self.recent_box.append(b)

    # ------------------------------------------------------------------ actions
    def launch(self, app):
        try:
            subprocess.Popen([APP_LAUNCHERS[app]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as e:
            self.game_msg.set_label(f'Could not start {APP_TITLES[app]}: {e.strerror}')

    def open_keys(self, app=None):
        keys.KeysWindow(app, parent=self, on_change=self.refresh).present()

    def clear_key(self):
        ui.in_thread(lambda: keyring.clear(None), lambda *_: self.refresh())

    def set_override(self, app, on):
        s = common.load_settings(self.paths)
        s['override'][app] = on
        common.save_settings(s, self.paths)
        has = self.status and self.status['overrides'][app]['override_stored']
        if on and not has:
            self.open_keys(app)
        self.refresh()

    def _reuse_set(self, _sw, state):
        if not self._syncing:
            s = common.load_settings(self.paths)
            s['reuse_agent_key'] = state
            common.save_settings(s, self.paths)
            self.refresh()
        return False

    def _model_changed(self, dd, _p):
        if self._syncing:
            return
        s = common.load_settings(self.paths)
        s['model'] = MODELS[dd.get_selected()]['id']
        common.save_settings(s, self.paths)

    def _budget_changed(self, dd, _p):
        if self._syncing:
            return
        s = common.load_settings(self.paths)
        s['daily_budget_tokens'] = BUDGETS[dd.get_selected()][1]
        common.save_settings(s, self.paths)
        self.refresh()

    def _agent_set(self, _sw, state):
        if self._syncing:
            return False
        self.agent_msg.set_label('Working...')

        def done(msg, err):
            self.agent_msg.set_label(str(err) if err else msg)
            self.settings = common.load_settings(self.paths)
        ui.in_thread(lambda: agent_link.set_agent_tools(state, self.paths), done)
        return False

    def new_game(self):
        name = self.game_entry.get_text().strip()
        try:
            res = projects.new_game(name, self.paths)
        except common.StudioError as e:
            self.game_msg.set_label(str(e))
            return
        except OSError as e:
            self.game_msg.set_label(f'Could not create the folders: {e.strerror}')
            return
        self.game_entry.set_text('')
        self.game_msg.set_label(f'Created {res["slug"]} in {self.paths.studio_root}')
        self.refresh_recent()

    def open_doc(self, name):
        for base in ('/usr/share/doc/amerika-studio', str(Path(__file__).resolve().parents[4] / 'docs/studio')):
            p = Path(base) / name
            if p.is_file():
                Gio.AppInfo.launch_default_for_uri(p.as_uri(), None)
                return
        self.game_msg.set_label('The documentation is not installed.')


class HubApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.amerika.Studio', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cmdline):
        if self.win is None:
            ui.setup()
            self.win = Hub(self)
        self.win.present()
        return 0


def main(argv=None):
    return HubApp().run(argv if argv is not None else sys.argv)


if __name__ == '__main__':
    sys.exit(main())
