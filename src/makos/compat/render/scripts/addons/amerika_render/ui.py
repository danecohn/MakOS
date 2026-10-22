"""Blender UI: the Amerika sidebar tab / workspace, operators, preferences and add-on lifecycle (main thread)."""
import atexit
import os
import textwrap
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup

from . import config, control, prompt, session as session_mod, toolspecs

PKG = __package__
_state = {'server': None, 'last_version': -1, 'timer': False, 'review_text': None}
MODEL_ITEMS = [(m, m.replace('claude-', '').replace('-', ' ').title().replace('5 5', '5.5'), m) for m in config.MODELS]


def S():
    return session_mod.get_session()


def _sync(self, context):
    s = S()
    s.model = self.model
    s.review_run_python = self.review_run_python
    s.review_all = self.review_all


class AmerikaProps(PropertyGroup):
    text: StringProperty(name='Ask', description='Describe what to make or change, then press Send', default='')
    model: EnumProperty(name='Model', items=MODEL_ITEMS, default=config.DEFAULT_MODEL, update=_sync)
    review_run_python: BoolProperty(name='Review code before it runs', default=True, update=_sync,
                                    description='Show model-written Python and wait for your approval (recommended)')
    review_all: BoolProperty(name='Review every change', default=False, update=_sync,
                             description='Ask before every tool that changes the scene (slower)')
    show_log: BoolProperty(name='Show log', default=False)


class AmerikaPrefs(AddonPreferences):
    bl_idname = PKG

    project_dir: StringProperty(name='Project folder', subtype='DIR_PATH', default='',
                                description='Exports, renders and checkpoints stay inside this folder (default ~/Studio/Render)')
    control_enabled: BoolProperty(name='Let Amerika Agent control Render', default=True,
                                  description='Serve the loopback control endpoint (127.0.0.1, token protected)')

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, 'project_dir')
        col.prop(self, 'control_enabled')
        col.label(text='Talks only to the local Studio bridge (127.0.0.1:18890). No API key is stored in Blender.')
        wrap(col, config.NOTICE, 90)


def wrap(layout, text, width, icon='NONE', alert=False, scale=0.85):
    col = layout.column(align=True)
    col.scale_y = scale
    col.alert = alert
    for i, line in enumerate(textwrap.wrap(str(text), max(16, int(width))) or ['']):
        col.label(text=line, icon=icon if i == 0 else 'NONE')


def chars(context):
    try:
        return max(18, int(context.region.width / (7.2 * context.preferences.system.ui_scale)) - 4)
    except Exception:
        return 40


def short(text, n):
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + '...'


def project_dir_for_session():
    prefs = _prefs()
    if prefs and prefs.project_dir:
        config.PROJECT_OVERRIDE = bpy.path.abspath(prefs.project_dir)
    return config.project_dir()


def _prefs():
    try:
        return bpy.context.preferences.addons[PKG].preferences
    except (KeyError, AttributeError):
        return None


def poll_idle(cls, context):
    return not S().busy


class AMERIKA_OT_send(Operator):
    bl_idname = 'amerika.send'
    bl_label = 'Send'
    bl_description = 'Send your request to the assistant'
    workflow: StringProperty(default='')

    def execute(self, context):
        props = context.window_manager.amerika_render
        text = props.text.strip()
        s = S()
        if s.busy:
            self.report({'WARNING'}, 'Still working on the previous request')
            return {'CANCELLED'}
        if self.workflow:
            if self.workflow in ('describe', 'change') and not text:
                self.report({'WARNING'}, 'Type what you want first')
                return {'CANCELLED'}
            message = prompt.workflow_prompt(self.workflow, text)
        else:
            if not text:
                return {'CANCELLED'}
            message = text
        _sync(props, context)
        project_dir_for_session()
        s.project_dir = str(config.project_dir())
        if not s.start(message, workflow=self.workflow or None):
            return {'CANCELLED'}
        props.text = ''
        ensure_timers()
        return {'FINISHED'}


class AMERIKA_OT_ask(Operator):
    bl_idname = 'amerika.ask'
    bl_label = 'Ask Render'
    bl_description = 'Type a request in a larger box and press Enter'
    text: StringProperty(name='Ask', default='')

    def invoke(self, context, event):
        self.text = context.window_manager.amerika_render.text
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        self.layout.prop(self, 'text', text='')

    def execute(self, context):
        context.window_manager.amerika_render.text = self.text
        return bpy.ops.amerika.send()


class AMERIKA_OT_stop(Operator):
    bl_idname = 'amerika.stop'
    bl_label = 'Stop'
    bl_description = 'Stop the assistant after the current step'

    def execute(self, context):
        S().stop()
        return {'FINISHED'}


class AMERIKA_OT_approve(Operator):
    bl_idname = 'amerika.approve'
    bl_label = 'Run'
    bl_description = 'Approve and run the shown code'

    def execute(self, context):
        S().decide(True)
        return {'FINISHED'}


class AMERIKA_OT_reject(Operator):
    bl_idname = 'amerika.reject'
    bl_label = 'Reject'
    bl_description = 'Do not run this'

    def execute(self, context):
        S().decide(False)
        return {'FINISHED'}


class AMERIKA_OT_undo_request(Operator):
    bl_idname = 'amerika.undo_request'
    bl_label = 'Undo last request'
    bl_description = 'Return the scene to the checkpoint saved when the last request started'

    @classmethod
    def poll(cls, context):
        return not S().busy

    def execute(self, context):
        out = S().undo_request()
        if not out.get('ok'):
            self.report({'WARNING'}, str(out.get('error')))
            return {'CANCELLED'}
        return {'FINISHED'}


class AMERIKA_OT_new_chat(Operator):
    bl_idname = 'amerika.new_chat'
    bl_label = 'New chat'
    bl_description = 'Forget the conversation (the scene is not changed)'

    @classmethod
    def poll(cls, context):
        return not S().busy

    def execute(self, context):
        S().new_chat()
        return {'FINISHED'}


class AMERIKA_OT_open_workspace(Operator):
    bl_idname = 'amerika.open_workspace'
    bl_label = 'Open Amerika workspace'

    def execute(self, context):
        ensure_workspace(context.window)
        return {'FINISHED'}


class AMERIKA_OT_about(Operator):
    bl_idname = 'amerika.about'
    bl_label = 'About Render'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420, confirm_text='Close')

    def draw(self, context):
        col = self.layout.column()
        col.label(text=f'Render {config.VERSION}', icon='LIGHT_SUN')
        wrap(col, config.NOTICE, 56)
        wrap(col, 'Blender license: GNU GPL v3 or later. Source: https://projects.blender.org', 56)

    def execute(self, context):
        return {'FINISHED'}


def draw_chat(layout, context, wide=None):
    s = S()
    props = context.window_manager.amerika_render
    w = wide or chars(context)
    head = layout.row(align=True)
    if s.busy:
        head.label(text='Working...', icon='SORTTIME')
        head.operator('amerika.stop', text='Stop', icon='CANCEL')
    else:
        head.label(text='Ready  -  ' + props.model.replace('claude-', ''), icon='CHECKMARK')
        head.operator('amerika.new_chat', text='', icon='TRASH')
    req = s.pending
    if req:
        rb = layout.box()
        rb.label(text=f'Review before running: {req["name"]}', icon='QUESTION')
        code = req.get('code') or str(req.get('input'))
        lines = code.splitlines()
        col = rb.column(align=True)
        col.scale_y = 0.75
        for line in lines[:16]:
            col.label(text=short(line.replace('\t', '    '), w + 8))
        if len(lines) > 16:
            col.label(text=f'... {len(lines) - 16} more lines (Text Editor: "Amerika Review")')
        row = rb.row(align=True)
        row.scale_y = 1.4
        row.operator('amerika.approve', text='Run', icon='PLAY')
        row.operator('amerika.reject', text='Reject', icon='X')
    col = layout.column(align=True)
    col.prop(props, 'text', text='', icon='LIGHT_SUN')
    row = col.row(align=True)
    row.scale_y = 1.3
    row.enabled = not s.busy
    row.operator('amerika.send', text='Send', icon='PLAY').workflow = ''
    row.operator('amerika.ask', text='', icon='TEXT')
    box = layout.box()
    shown = [e for e in s.events if e['kind'] in ('user', 'assistant', 'tool_end', 'error', 'note', 'review')][-14:]
    if not shown:
        wrap(box, 'Tell me what to make or change. Try: "a low-poly pine tree, 3 m tall".', w, 'INFO')
    for e in shown:
        k = e['kind']
        if k == 'user':
            wrap(box, 'You: ' + short(e.get('text', ''), 200), w, 'USER')
        elif k == 'assistant':
            wrap(box, e.get('text', '')[:700], w, 'LIGHT_SUN')
        elif k == 'tool_end':
            wrap(box, e.get('label') or e['name'], w, 'CHECKMARK' if e.get('ok') else 'ERROR', alert=not e.get('ok'), scale=0.75)
        elif k == 'error':
            wrap(box, e.get('text') or e.get('message', ''), w, 'ERROR', alert=True)
        elif k == 'review':
            wrap(box, 'Waiting for your approval', w, 'QUESTION', scale=0.75)
        else:
            wrap(box, e.get('text', ''), w, 'DOT', scale=0.75)


def _mirror_review_text(code):
    if _state['review_text'] == code:
        return
    _state['review_text'] = code
    try:
        t = bpy.data.texts.get('Amerika Review') or bpy.data.texts.new('Amerika Review')
        t.clear()
        t.write(code)
    except Exception:
        pass


class AMERIKA_PT_chat(Panel):
    bl_label = 'Render'
    bl_idname = 'AMERIKA_PT_chat'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Amerika'

    def draw_header(self, context):
        self.layout.label(icon='LIGHT_SUN')

    def draw(self, context):
        draw_chat(self.layout, context)


class AMERIKA_PT_workflows(Panel):
    bl_label = 'Workflows'
    bl_idname = 'AMERIKA_PT_workflows'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Amerika'

    def draw(self, context):
        s = S()
        col = self.layout.column(align=True)
        col.enabled = not s.busy
        for kind, icon in (('describe', 'MESH_MONKEY'), ('change', 'MODIFIER'), ('game_ready', 'EXPORT'), ('rig', 'ARMATURE_DATA')):
            op = col.operator('amerika.send', text=prompt.WORKFLOWS[kind][0], icon=icon)
            op.workflow = kind
        wrap(self.layout, 'The text box above is used as the description / instruction.', chars(context), 'INFO', scale=0.75)


class AMERIKA_PT_options(Panel):
    bl_label = 'Options'
    bl_idname = 'AMERIKA_PT_options'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Amerika'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        props = context.window_manager.amerika_render
        col = self.layout.column()
        col.prop(props, 'model')
        col.prop(props, 'review_run_python')
        col.prop(props, 'review_all')
        col.operator('amerika.undo_request', icon='LOOP_BACK')
        col.operator('amerika.open_workspace', icon='WORKSPACE')
        col.separator()
        srv = _state['server']
        col.label(text=('Agent control: on (port %d)' % srv.port) if srv else 'Agent control: off', icon='LINKED' if srv else 'UNLINKED')
        col.label(text='Project: ' + short(str(config.project_dir()), 40), icon='FILE_FOLDER')
        col.operator('amerika.about', icon='INFO')


class AMERIKA_PT_log(Panel):
    bl_label = 'Activity log'
    bl_idname = 'AMERIKA_PT_log'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Amerika'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = S()
        col = self.layout.column(align=True)
        col.scale_y = 0.75
        calls = [e for e in s.events if e['kind'] in ('tool_start', 'tool_end', 'review', 'error')][-40:]
        w = chars(context)
        for e in calls:
            stamp = time.strftime('%H:%M:%S', time.localtime(e['time']))
            if e['kind'] == 'tool_start':
                col.label(text=short(f'{stamp} > {e["name"]} {e.get("input")}', w + 12))
            elif e['kind'] == 'tool_end':
                col.label(text=short(f'{stamp} {"ok " if e.get("ok") else "ERR"} {e["name"]}', w + 12))
            else:
                col.label(text=short(f'{stamp} {e["kind"]}: {e.get("text") or e.get("name") or e.get("message", "")}', w + 12))
        if not calls:
            col.label(text='No activity yet.')


def tag_redraw():
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in ('VIEW_3D', 'TEXT_EDITOR', 'PROPERTIES'):
                area.tag_redraw()


def _redraw_tick():
    s = S()
    req = s.pending
    if req:
        _mirror_review_text(req.get('code') or str(req.get('input')))
    if s.version != _state['last_version']:
        _state['last_version'] = s.version
        try:
            tag_redraw()
        except Exception:
            pass
    return 0.3


def ensure_timers():
    if not _state['timer']:
        bpy.app.timers.register(_redraw_tick, first_interval=0.3, persistent=True)
        _state['timer'] = True
    S().main.start_timer()


def ensure_workspace(window=None):
    """Create (once) and activate the 'Amerika' workspace: a 3D view with the Amerika tab open. GUI sessions only."""
    if bpy.app.background:
        return None
    wm = bpy.context.window_manager
    window = window or (wm.windows[0] if wm.windows else None)
    if window is None:
        return None
    ws = bpy.data.workspaces.get('Amerika')
    if ws is None:
        base = bpy.data.workspaces.get('Layout') or window.workspace
        window.workspace = base
        before = set(w.name for w in bpy.data.workspaces)
        with bpy.context.temp_override(window=window):
            bpy.ops.workspace.duplicate()
        new = [w for w in bpy.data.workspaces if w.name not in before]
        if not new:
            return None
        ws = new[0]
        ws.name = 'Amerika'
        window.workspace = ws
        _layout_workspace(ws)
    else:
        window.workspace = ws
    return ws


def _layout_workspace(ws):
    """3D viewport on the left, a wide Properties editor showing the chat on the right.
    Blender applies workspace switches on the next event loop pass, so the steps run from timers."""
    def step1():
        win = next((w for w in bpy.context.window_manager.windows if w.workspace == ws), None)
        if win is None:
            return None
        outliner = None
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.show_region_ui = False
                area.spaces.active.shading.type = 'SOLID'
            elif area.type == 'PROPERTIES':
                try:
                    area.spaces.active.context = 'SCENE'
                except Exception as e:
                    print('amerika_render: could not select the Tool tab:', e)
            elif area.type == 'OUTLINER':
                outliner = area
        if outliner is not None:
            try:
                with bpy.context.temp_override(window=win, screen=win.screen, area=outliner, region=outliner.regions[-1]):
                    bpy.ops.screen.area_move(x=outliner.x, y=outliner.y + outliner.height // 2, delta=-330)
            except Exception as e:  # layout is cosmetic
                print('amerika_render: could not widen the chat column:', e)
        return None
    bpy.app.timers.register(step1, first_interval=0.5)


def _apply_defaults_once():
    """Called a moment after the window exists (startup script / handler)."""
    if bpy.app.background:
        return None
    try:
        ensure_workspace()
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.spaces.active.show_region_ui = True
    except Exception as e:  # never break startup
        print('amerika_render: workspace setup skipped:', e)
    return None


def _in_amerika_ws(context):
    ws = getattr(context, 'workspace', None)
    return bool(ws) and ws.name == 'Amerika'


def _variants():
    """Blender cannot select a sidebar tab from Python. So the 'Amerika' workspace shows the same panels in a wide Properties
    editor (its 'Scene' tab, selected from Python) next to the 3D viewport. In every other workspace they live in the 3D
    viewport's 'Amerika' sidebar tab."""
    out = []
    for n, cls in enumerate((AMERIKA_PT_chat, AMERIKA_PT_workflows, AMERIKA_PT_options, AMERIKA_PT_log)):
        ws = type(cls.__name__ + '_WS', (cls,), {
            'bl_idname': cls.bl_idname + '_WS', 'bl_space_type': 'PROPERTIES', 'bl_region_type': 'WINDOW', 'bl_context': 'scene',
            'bl_category': '', 'bl_order': -100 + n,
            'poll': classmethod(lambda c, context: _in_amerika_ws(context)),
        })
        out.append(ws)
    return out


_WS_PANELS = _variants()

CLASSES = (AmerikaProps, AmerikaPrefs, AMERIKA_OT_send, AMERIKA_OT_ask, AMERIKA_OT_stop, AMERIKA_OT_approve, AMERIKA_OT_reject,
           AMERIKA_OT_undo_request, AMERIKA_OT_new_chat, AMERIKA_OT_open_workspace, AMERIKA_OT_about,
           AMERIKA_PT_chat, AMERIKA_PT_workflows, AMERIKA_PT_options, AMERIKA_PT_log, *_WS_PANELS)
_keymaps = []


def start_control(session=None, descriptor=None):
    if _state['server']:
        return _state['server']
    s = session or S()
    srv = control.Server(s)
    srv.start(descriptor)
    _state['server'] = srv
    return srv


def stop_control():
    srv = _state['server']
    if srv:
        srv.stop()
        _state['server'] = None


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.amerika_render = PointerProperty(type=AmerikaProps)
    wm = bpy.context.window_manager
    if wm and wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name='Window', space_type='EMPTY')
        kmi = km.keymap_items.new('amerika.ask', 'A', 'PRESS', ctrl=True, alt=True)
        _keymaps.append((km, kmi))
    s = S()
    s.project_dir = None
    if not bpy.app.background:
        ensure_timers()
    prefs = _prefs()
    if prefs and prefs.project_dir:
        config.PROJECT_OVERRIDE = bpy.path.abspath(prefs.project_dir)
    if os.environ.get('AMERIKA_RENDER_NO_CONTROL') != '1' and not bpy.app.background and (prefs is None or prefs.control_enabled):
        try:
            start_control(s)
        except OSError as e:
            print('amerika_render: control endpoint not started:', e)
    atexit.register(stop_control)


def unregister():
    stop_control()
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymaps.clear()
    del bpy.types.WindowManager.amerika_render
    for c in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass
