"""Render startup script (passed by the launcher with --python).

Enables the amerika_render add-on, applies the Amerika theme, and opens the Amerika workspace.
Runs inside Blender; must never raise.
"""
import os
import sys

import bpy

SHARE = os.environ.get('AMERIKA_RENDER_SHARE', '/usr/share/amerika-render')


def _enable_addon():
    import addon_utils
    try:
        addon_utils.enable('amerika_render', default_set=True, persistent=True)
    except Exception as e:  # noqa: BLE001
        print('amerika_render: could not enable the add-on:', e)


def _theme():
    path = os.path.join(SHARE, 'theme', 'amerika.xml')
    if os.environ.get('AMERIKA_RENDER_KEEP_THEME') == '1' or not os.path.exists(path):
        return
    try:
        bpy.ops.script.execute_preset(filepath=path, menu_idname='USERPREF_MT_interface_theme_presets')
    except Exception as e:  # noqa: BLE001
        print('amerika_render: theme not applied:', e)


def _prefs():
    try:
        p = bpy.context.preferences
        p.view.show_splash = True
        p.view.show_tooltips_python = False
        p.view.ui_line_width = 'AUTO'
        p.view.use_translate_new_dataname = False
        p.filepaths.use_auto_save_temporary_files = True
        p.use_preferences_save = False
    except Exception as e:  # noqa: BLE001
        print('amerika_render: preferences skipped:', e)


def _workspace():
    try:
        from amerika_render import ui
        ui._apply_defaults_once()
    except Exception as e:  # noqa: BLE001
        print('amerika_render: workspace skipped:', e)
    return None


_enable_addon()
_theme()
_prefs()
if not bpy.app.background:
    bpy.app.timers.register(_workspace, first_interval=0.4)
