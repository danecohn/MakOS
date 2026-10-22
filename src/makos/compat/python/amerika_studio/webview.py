"""amerika-studio-webview: the shared WebKitGTK shell for Sprite and MakBox. See docs/studio/webview.md."""
import argparse
import atexit
import base64
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('WebKit', '6.0')
gi.require_version('JavaScriptCore', '6.0')
from gi.repository import Gdk, Gio, GLib, Gtk, JavaScriptCore, WebKit  # noqa: E402

from . import __version__, client, common, confine, ui, webcore  # noqa: E402
from .common import StudioError  # noqa: E402
from .webcore import RpcFail  # noqa: E402

BG = Gdk.RGBA(red=0.043, green=0.039, blue=0.078, alpha=1)


def read_web(name):
    p = webcore.SHARED_WEB / name
    if not p.is_file():
        p = Path(__file__).resolve().parent.parent / 'web' / name
    return p.read_text(encoding='utf-8')


class StudioWebWindow(Gtk.ApplicationWindow):
    def __init__(self, application, app, appdir, entry, project_dir, title=None, paths=None):
        self.spec = webcore.SPECS[app]
        super().__init__(application=application, title=title or self.spec['title'])
        self.add_css_class('st-window')
        self.set_default_size(1280, 820)
        self.set_icon_name(self.spec['icon'])
        self.app, self.appdir, self.entry = app, Path(appdir).resolve(), entry
        self.paths = paths or common.Paths()
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.base_title = title or self.spec['title']
        self.grants = webcore.Grants(self.project_dir)
        self.recent = webcore.Recent(self.paths, app)
        for p in self.recent.list():
            self.grants.grant(p)
        self.dirty = False
        self._force_close = False
        self.page_ready_rpc = False
        self.page_ready_open = False
        self.pending_files = []
        self.pending = webcore.Pending()
        self.bridge = client.BridgeClient('sprite' if app == 'sprite' else 'box', paths=self.paths)
        self._bridge_ensured = False
        self.roots = [self.appdir, webcore.SHARED_WEB]
        self._build_ui()
        self._build_web()
        self.control = webcore.ControlServer(app, self.handle_rpc, self.paths)
        self.control.start()
        atexit.register(self.control.stop)
        self.connect('close-request', self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        header = Gtk.HeaderBar()
        self.title_label = ui.label(self.base_title, 'am-agent-title')
        header.set_title_widget(self.title_label)
        open_btn = ui.button('Open', 'am-secondary', self.open_dialog)
        header.pack_start(open_btn)
        self.recent_btn = Gtk.MenuButton(label='Recent')
        self.recent_btn.add_css_class('am-secondary')
        self.recent_pop = Gtk.Popover()
        self.recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.recent_pop.set_child(self.recent_box)
        self.recent_btn.set_popover(self.recent_pop)
        self.recent_pop.connect('show', lambda *_: self._fill_recent())
        header.pack_start(self.recent_btn)
        header.pack_end(ui.button('Keys...', 'am-secondary', self.open_keys))
        self.set_titlebar(header)
        self.stack = Gtk.Overlay()
        self.set_child(self.stack)

    def _fill_recent(self):
        ui.clear(self.recent_box)
        items = self.recent.list()
        if not items:
            self.recent_box.append(ui.label('No recent files', 'am-sub'))
        for p in items:
            b = Gtk.Button(label=os.path.basename(p), has_frame=False)
            b.set_tooltip_text(p)
            b.connect('clicked', lambda _b, path=p: (self.recent_pop.popdown(), self.open_path(path)))
            self.recent_box.append(b)
        if items:
            self.recent_box.append(ui.button('Clear list', 'st-link', lambda: (self.recent.clear(), self.recent_pop.popdown())))

    def open_keys(self):
        try:
            subprocess.Popen(['amerika-studio-keys', '--app', self.app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ web view
    def _build_web(self):
        data = self.paths.data_dir / self.app / 'webdata'
        cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'amerika-studio' / self.app
        for d in (data, cache):
            common.ensure_private_dir(d)
        session = WebKit.NetworkSession.new(str(data), str(cache))
        session.connect('download-started', lambda _s, dl: dl.cancel())
        self.ucm = WebKit.UserContentManager()
        info = {'app': self.app, 'version': __version__, 'projectDir': str(self.project_dir), 'shell': 'amerika-studio-webview'}
        src = read_web('shell.js').replace('__AMERIKA_INFO__', json.dumps(info)) + '\n' + read_web('ai-client.js')
        self.ucm.add_script(WebKit.UserScript.new(src, WebKit.UserContentInjectedFrames.TOP_FRAME,
                                                  WebKit.UserScriptInjectionTime.START, None, None))
        self.ucm.connect('script-message-with-reply-received::amerika', self._on_message)
        self.ucm.register_script_message_handler_with_reply('amerika', None)
        self._filter_store = WebKit.UserContentFilterStore.new(str(cache / 'filters'))
        rules = json.dumps([{'trigger': {'url-filter': pat}, 'action': {'type': 'block'}} for pat in (r'^https?://', r'^wss?://', r'^ftp://')])
        self._filter_store.save('amerika-studio-no-network', GLib.Bytes.new(rules.encode()), None, self._filter_saved)
        self.web = WebKit.WebView(network_session=session, user_content_manager=self.ucm)
        st = self.web.get_settings()
        for name, value in (('enable_developer_extras', os.environ.get('AMERIKA_STUDIO_DEVTOOLS') == '1'),
                            ('enable_write_console_messages_to_stdout', os.environ.get('AMERIKA_STUDIO_DEVTOOLS') == '1'),
                            ('enable_media_stream', False), ('enable_webrtc', False), ('javascript_can_open_windows_automatically', False),
                            ('allow_file_access_from_file_urls', True), ('allow_universal_access_from_file_urls', False),
                            ('enable_webaudio', True), ('enable_html5_local_storage', True), ('enable_java', False)):
            try:
                getattr(st, 'set_' + name)(value)
            except (AttributeError, TypeError):
                pass
        self.web.set_background_color(BG)
        self.web.set_hexpand(True)
        self.web.set_vexpand(True)
        self.web.connect('decide-policy', self._decide)
        self.web.connect('permission-request', lambda _v, request: (request.deny(), True)[1])
        self.web.connect('context-menu', lambda *_: os.environ.get('AMERIKA_STUDIO_DEVTOOLS') != '1')
        self.web.connect('load-failed', self._load_failed)
        self.web.connect('web-process-terminated', self._crashed)
        self.web.connect('load-changed', self._load_changed)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drop.connect('drop', self._on_drop)
        self.web.add_controller(drop)
        self.stack.set_child(self.web)

    def _filter_saved(self, store, res):
        """The content blocker (no http/https/ws/ftp request from the page, whatever the page does) is in place before the
        first page load; if it cannot be installed the page is not loaded at all."""
        try:
            self.ucm.add_filter(store.save_finish(res))
        except GLib.Error as e:
            self._show_problem(f'Could not install the network filter ({e.message}); refusing to load the app.')
            return
        self.web.load_uri((self.appdir / self.entry).as_uri())

    def _decide(self, view, decision, dtype):
        kinds = WebKit.PolicyDecisionType
        try:
            if dtype in (kinds.NAVIGATION_ACTION, kinds.NEW_WINDOW_ACTION):
                uri = decision.get_navigation_action().get_request().get_uri() or ''
                if dtype == kinds.NAVIGATION_ACTION and webcore.uri_allowed(uri, self.roots):
                    decision.use()
                else:
                    decision.ignore()
                return True
            if dtype == kinds.RESPONSE:
                decision.use() if decision.is_mime_type_supported() else decision.ignore()
                return True
        except (GLib.Error, AttributeError):
            decision.ignore()
            return True
        return False

    def _load_changed(self, _view, event):
        if event == WebKit.LoadEvent.STARTED:
            self.page_ready_rpc = False
            self.page_ready_open = False

    def _load_failed(self, _view, _event, uri, error):
        self._show_problem(f'Could not load the app page ({uri}): {error.message}')
        return True

    def _crashed(self, _view, reason):
        self._show_problem('The page process stopped. Close and reopen the window.')

    def _show_problem(self, text):
        lab = ui.label(text, 'am-sub', wrap=True)
        lab.set_halign(Gtk.Align.CENTER)
        lab.set_valign(Gtk.Align.START)
        lab.add_css_class('am-agent-banner')
        self.stack.add_overlay(lab)

    # ------------------------------------------------------------------ script messages (page -> shell)
    def _on_message(self, _ucm, value, reply):
        ctx = value.get_context()

        def answer(result=None, error=None):
            def send():
                payload = {'error': error} if error else {'result': result}
                reply.return_value(JavaScriptCore.Value.new_string(ctx, json.dumps(payload)))
                return False
            GLib.idle_add(send)
        try:
            msg = json.loads(value.to_json(0))
            cmd, args = msg['cmd'], msg.get('args') or {}
            if not isinstance(cmd, str) or not isinstance(args, dict):
                raise RpcFail(-32602, 'bad message')
            self._dispatch(cmd, args, answer)
        except RpcFail as e:
            answer(error={'code': e.code, 'message': str(e)})
        except StudioError as e:
            answer(error={'code': getattr(e, 'rpc_code', -32000), 'message': str(e)})
        except Exception as e:  # noqa: BLE001 - the page gets an error, never a hang
            answer(error={'code': -32000, 'message': f'{type(e).__name__}: {e}'})
        return True

    def _dispatch(self, cmd, args, answer):
        if cmd == 'request':
            return self._bridge_request(args, answer)
        if cmd == 'fs.open':
            return self._fs_open(args, answer)
        if cmd == 'fs.save':
            return self._fs_save(args, answer)
        if cmd == 'fs.readFile':
            path = str(args.get('path', ''))
            if not self.grants.allowed(path):
                raise RpcFail(-32003, 'path_not_allowed: only files you opened or saved, or the project folder')
            return answer(webcore.read_for_page(path, bool(args.get('binary'))))
        if cmd == 'fs.writeProject':
            raw = webcore.decode_data(args.get('data'), args.get('encoding', 'utf8'))
            p = confine.resolve_in(self.project_dir, args.get('path'))
            if p.exists() and not args.get('overwrite'):
                raise RpcFail(-32000, 'exists: pass overwrite:true to replace the file')
            if p.is_symlink() or p.is_dir() or not confine.is_inside(self.project_dir, p.parent):
                raise confine.ConfineError('refusing to write there')
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + '.part')
            tmp.write_bytes(raw)
            os.replace(tmp, p)
            self.grants.grant(p)
            return answer({'path': str(p), 'bytes': len(raw)})
        if cmd == 'fs.listProject':
            return answer(confine.list_dir(self.project_dir, str(args.get('path', '.')), False, 2000))
        if cmd == 'recent.list':
            return answer(self.recent.list())
        if cmd == 'recent.add':
            path = str(args.get('path', ''))
            if not self.grants.allowed(path):
                raise RpcFail(-32003, 'path_not_allowed')
            return answer(self.recent.add(path))
        if cmd == 'recent.clear':
            self.recent.clear()
            return answer({'ok': True})
        if cmd == 'window.setTitle':
            title = str(args.get('title', ''))[:200]
            GLib.idle_add(lambda: (self.set_title(f'{title} - {self.base_title}' if title else self.base_title),
                                   self.title_label.set_label(f'{title} - {self.base_title}' if title else self.base_title), False)[2])
            return answer({'ok': True})
        if cmd == 'window.setDirty':
            self.dirty = bool(args.get('dirty'))
            return answer({'ok': True})
        if cmd == 'window.close':
            self._force_close = True
            GLib.idle_add(lambda: (self.close(), False)[1])
            return answer({'ok': True})
        if cmd == 'rpc.ready':
            self.page_ready_rpc = bool(args.get('ready'))
            return answer({'ok': True})
        if cmd == 'open.ready':
            self.page_ready_open = bool(args.get('ready'))
            if self.page_ready_open:
                GLib.idle_add(self._flush_pending)
            return answer({'ok': True})
        if cmd == 'rpc.result':
            self.pending.resolve(str(args.get('id')), args.get('result'), args.get('error'))
            return answer({'ok': True})
        raise RpcFail(-32601, f'unknown command {cmd}')

    # ------------------------------------------------------------------ bridge proxy
    def _bridge_request(self, args, answer):
        method, path = webcore.check_bridge_request(args.get('path'), args.get('body'))
        body = args.get('body')
        timeout = args.get('timeoutMs')
        timeout = max(5, min(900, int(timeout) / 1000)) if isinstance(timeout, (int, float)) else 300

        def work():
            self.bridge.timeout = timeout
            try:
                return self._call_bridge(method, path, body)
            except client.ApiError as e:
                if e.kind == 'bridge_down' and not self._bridge_ensured:
                    self._bridge_ensured = True
                    from . import cli
                    cli.ensure_bridge()
                    return self._call_bridge(method, path, body)
                raise

        def done(result, err):
            if err:
                kind = getattr(err, 'kind', 'error')
                answer(error={'code': -32000, 'error': kind, 'message': str(err)})
            else:
                answer(result)
        ui.in_thread(work, done)

    def _call_bridge(self, method, path, body):
        status, parsed, retry = self.bridge._request(method, path, body)
        headers = {'retry-after': str(retry)} if retry else {}
        return {'status': status, 'json': parsed, 'headers': headers}

    # ------------------------------------------------------------------ file dialogs
    def _filters(self, args):
        flt = args.get('filters') or [{'name': n, 'patterns': p} for n, p in self.spec['filters']]
        store = Gio.ListStore.new(Gtk.FileFilter)
        for f in flt[:8]:
            ff = Gtk.FileFilter()
            ff.set_name(str(f.get('name', 'Files')))
            for pat in (f.get('patterns') or ['*'])[:20]:
                ff.add_pattern(str(pat))
            store.append(ff)
        return store

    def open_dialog(self):
        self._fs_open({}, lambda result=None, error=None: self._deliver(result) if result else None)

    def _fs_open(self, args, answer):
        dlg = Gtk.FileDialog()
        dlg.set_title(str(args.get('title') or 'Open'))
        dlg.set_filters(self._filters(args))
        dlg.set_initial_folder(Gio.File.new_for_path(str(self.project_dir)))

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return answer(None)
            path = f.get_path()
            try:
                self.grants.grant(path)
                binary = bool(args.get('binary')) or webcore.is_binary(path, self.spec)
                out = webcore.read_for_page(path, binary)
                self.recent.add(path)
                answer(out)
            except RpcFail as e:
                answer(error={'code': e.code, 'message': str(e)})
        dlg.open(self, None, done)

    def _fs_save(self, args, answer):
        raw = webcore.decode_data(args.get('data'), args.get('encoding', 'utf8'))
        dlg = Gtk.FileDialog()
        dlg.set_title(str(args.get('title') or 'Save'))
        dlg.set_filters(self._filters(args))
        dlg.set_initial_folder(Gio.File.new_for_path(str(self.project_dir)))
        name = os.path.basename(str(args.get('suggestedName') or ''))
        if name:
            dlg.set_initial_name(name)

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return answer(None)
            try:
                path = f.get_path()
                Path(path).write_bytes(raw)
                self.grants.grant(path)
                self.recent.add(path)
                answer({'path': path, 'name': os.path.basename(path)})
            except OSError as e:
                answer(error={'code': -32000, 'message': f'cannot write the file: {e.strerror}'})
        dlg.save(self, None, done)

    # ------------------------------------------------------------------ opening files in the page
    def _on_drop(self, _target, value, _x, _y):
        for f in value.get_files():
            if f.get_path():
                self.open_path(f.get_path())
        return True

    def open_path(self, path):
        try:
            self.grants.grant(path)
            data = webcore.read_for_page(path, webcore.is_binary(path, self.spec))
            self.recent.add(path)
        except RpcFail as e:
            self._show_problem(str(e))
            return
        self._deliver(data)

    def _deliver(self, file):
        if not self.page_ready_open:
            self.pending_files.append(file)
            return
        self.web.evaluate_javascript(f'amerikaStudio.__dispatchOpen({json.dumps(file)})', -1, None, None, None, None)

    def _flush_pending(self):
        files, self.pending_files = self.pending_files, []
        for f in files:
            self._deliver(f)
        return False

    # ------------------------------------------------------------------ control endpoint (called from its HTTP thread)
    def handle_rpc(self, name, params, timeout):
        if name == 'app.ping':
            return {'ok': True, 'app': self.app, 'version': __version__, 'ready': self.page_ready_rpc}
        if name == 'app.open':
            path = str(params.get('path', ''))
            if not os.path.isfile(path):
                raise RpcFail(-32602, 'no such file')
            GLib.idle_add(lambda: (self.open_path(path), False)[1])
            return {'ok': True}
        if name == 'app.screenshot':
            return self._screenshot(timeout)
        if not self.page_ready_rpc:
            raise RpcFail(-32004, 'the app is not ready yet')
        rid = self.pending.new()

        def run():
            js = f'amerikaStudio.__dispatchRpc({json.dumps(rid)}, {json.dumps(name)}, {json.dumps(params)})'
            self.web.evaluate_javascript(js, -1, None, None, None, None)
            return False
        GLib.idle_add(run)
        return self.pending.wait(rid, timeout)

    def _screenshot(self, timeout):
        rid = self.pending.new()

        def done(view, res):
            try:
                tex = view.get_snapshot_finish(res)
                png = tex.save_to_png_bytes().get_data()
                self.pending.resolve(rid, {'images': [{'mime': 'image/png', 'base64': base64.b64encode(png).decode()}],
                                           'width': tex.get_width(), 'height': tex.get_height()})
            except GLib.Error as e:
                self.pending.resolve(rid, error={'code': -32000, 'message': e.message})

        def run():
            self.web.get_snapshot(WebKit.SnapshotRegion.VISIBLE, WebKit.SnapshotOptions.NONE, None, done)
            return False
        GLib.idle_add(run)
        return self.pending.wait(rid, timeout)

    # ------------------------------------------------------------------ closing
    def _on_close(self, _win):
        if self.dirty and not self._force_close:
            dlg = Gtk.AlertDialog()
            dlg.set_message('Discard unsaved changes?')
            dlg.set_detail('This window has changes that were not saved.')
            dlg.set_buttons(['Keep editing', 'Discard'])
            dlg.set_cancel_button(0)
            dlg.set_default_button(0)

            def done(d, res):
                try:
                    if d.choose_finish(res) == 1:
                        self._force_close = True
                        self.close()
                except GLib.Error:
                    pass
            dlg.choose(self, None, done)
            return True
        self.control.stop()
        return False


class WebApp(Gtk.Application):
    def __init__(self, args):
        spec = webcore.SPECS[args.app]
        super().__init__(application_id=args.app_id or spec['app_id'], flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = args
        self.win = None

    def do_command_line(self, cmdline):
        files = []
        for a in cmdline.get_arguments()[1:]:
            if a.startswith('-'):
                continue
            files.append(a if os.path.isabs(a) else os.path.join(cmdline.get_cwd() or '.', a))
        if self.win is None:
            ui.setup()
            c = self.cfg
            project = c.project_dir or common.Paths().project_dir(c.app)
            self.win = StudioWebWindow(self, c.app, c.dir, c.entry, project, c.title)
            if c.icon:
                self.win.set_icon_name(c.icon)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, lambda: (self.win.control.stop(), self.quit(), False)[2])
        for f in files:
            self.win.open_path(f)
        self.win.present()
        return 0


def parse_args(argv):
    p = argparse.ArgumentParser(prog='amerika-studio-webview', description='Shared WebKitGTK shell for Sprite and MakBox')
    p.add_argument('--app', required=True, choices=sorted(webcore.SPECS))
    p.add_argument('--dir', required=True, help='directory of the web app')
    p.add_argument('--entry', default='index.html')
    p.add_argument('--title')
    p.add_argument('--icon')
    p.add_argument('--app-id')
    p.add_argument('--project-dir')
    args, rest = p.parse_known_args(argv)
    if not (Path(args.dir) / args.entry).is_file():
        p.error(f'{Path(args.dir) / args.entry} does not exist')
    return args, rest


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    args, files = parse_args(argv)
    return WebApp(args).run([sys.argv[0]] + [f for f in files if not f.startswith('--')])


if __name__ == '__main__':
    sys.exit(main())
