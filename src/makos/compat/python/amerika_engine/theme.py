"""Retro-futurist neon-on-chrome editor settings, seeded once into the Engine config directory."""
from pathlib import Path

MARK = '; amerika-engine theme v1'

SETTINGS = f"""{MARK}
[gd_resource type="EditorSettings" format=3]

[resource]
interface/theme/preset = "Custom"
interface/theme/base_color = Color(0.0549, 0.0314, 0.0627, 1)
interface/theme/accent_color = Color(1, 0.2392, 0.4314, 1)
interface/theme/contrast = 0.4
interface/theme/draw_extra_borders = true
interface/theme/corner_radius = 6
interface/editor/show_update_spinner = 1
interface/editor/update_continuously = false
network/connection/check_for_updates = 2
text_editor/theme/highlighting/symbol_color = Color(1, 0.69, 0.18, 1)
text_editor/theme/highlighting/keyword_color = Color(1, 0.24, 0.43, 1)
text_editor/theme/highlighting/control_flow_keyword_color = Color(1, 0.24, 0.43, 1)
text_editor/theme/highlighting/base_type_color = Color(0.24, 1, 0.69, 1)
text_editor/theme/highlighting/string_color = Color(1, 0.88, 0.3, 1)
text_editor/theme/highlighting/background_color = Color(0.05, 0.03, 0.09, 1)
"""


def seed(config_home):
    """config_home is the XDG_CONFIG_HOME used for Godot (Godot reads <it>/godot/). Never overwrites a user-modified file."""
    d = Path(config_home) / 'godot'
    d.mkdir(parents=True, exist_ok=True)
    f = d / 'editor_settings-4.tres'
    if f.exists() and MARK not in f.read_text():
        return f
    if not f.exists():
        f.write_text(SETTINGS)
    return f
