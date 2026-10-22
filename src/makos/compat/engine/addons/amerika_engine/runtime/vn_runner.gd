extends Control
## Visual-novel runner. Reads `story` from res://amerika_game.json:
##   {"start": "id", "characters": {"Mara": {"color": "#ff3d6e", "texture": "res://..png"}},
##    "nodes": {"id": {"speaker": "Mara", "text": "...", "bg": "#112233" | "res://bg.png", "next": "id2",
##              "choices": [{"text": "...", "goto": "id", "set_flag": "x", "if_flag": "y"}], "set_flag": "z", "end": true}}}

var story: Dictionary = {}
var current_id: String = ""
var finished: bool = false
var choices_visible: bool = false

var _nodes: Dictionary = {}
var _characters: Dictionary = {}
var _bg: ColorRect
var _bg_tex: TextureRect
var _portrait: TextureRect
var _name: Label
var _text: RichTextLabel
var _choices: VBoxContainer
var _hint: Label
var _typing: float = 0.0
var _accent := Color("ff3d6e")
var _txt := Color("fff0cf")
var _panel := Color("0e0810")
var _history: Array[String] = []


func _ready() -> void:
	var g := get_node_or_null("/root/AmerikaGame")
	if g != null:
		story = g.call("cfg", "story", {})
		_accent = Color(str(g.call("cfg", "theme.accent", "ff3d6e")))
		_txt = Color(str(g.call("cfg", "theme.text", "fff0cf")))
		_panel = Color(str(g.call("cfg", "theme.panel", "0e0810")))
		g.set("level", self)
		g.set("state", "playing")
	_nodes = story.get("nodes", {})
	_characters = story.get("characters", {})
	set_anchors_preset(Control.PRESET_FULL_RECT)
	_build()
	go(str(story.get("start", "")))


func _build() -> void:
	_bg = ColorRect.new()
	_bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	_bg.color = _panel
	add_child(_bg)
	_bg_tex = TextureRect.new()
	_bg_tex.set_anchors_preset(Control.PRESET_FULL_RECT)
	_bg_tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_bg_tex.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	add_child(_bg_tex)
	_portrait = TextureRect.new()
	_portrait.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	_portrait.anchor_left = 0.5
	_portrait.anchor_right = 0.5
	_portrait.anchor_top = 0.08
	_portrait.anchor_bottom = 0.72
	_portrait.offset_left = -240
	_portrait.offset_right = 240
	_portrait.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_portrait.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	add_child(_portrait)
	var box := PanelContainer.new()
	box.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	box.anchor_top = 0.72
	box.offset_left = 28
	box.offset_right = -28
	box.offset_bottom = -22
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(_panel, 0.9)
	sb.border_color = _accent
	sb.set_border_width_all(2)
	sb.set_corner_radius_all(10)
	sb.set_content_margin_all(14)
	box.add_theme_stylebox_override("panel", sb)
	add_child(box)
	var v := VBoxContainer.new()
	box.add_child(v)
	_name = Label.new()
	_name.add_theme_font_size_override("font_size", 24)
	_name.add_theme_color_override("font_color", _accent)
	v.add_child(_name)
	_text = RichTextLabel.new()
	_text.bbcode_enabled = true
	_text.fit_content = false
	_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_text.add_theme_font_size_override("normal_font_size", 22)
	_text.add_theme_color_override("default_color", _txt)
	v.add_child(_text)
	_hint = Label.new()
	_hint.text = "Enter / click to continue"
	_hint.add_theme_font_size_override("font_size", 14)
	_hint.add_theme_color_override("font_color", Color(_txt, 0.5))
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	v.add_child(_hint)
	_choices = VBoxContainer.new()
	_choices.set_anchors_preset(Control.PRESET_CENTER)
	_choices.anchor_left = 0.25
	_choices.anchor_right = 0.75
	_choices.anchor_top = 0.25
	_choices.anchor_bottom = 0.6
	_choices.alignment = BoxContainer.ALIGNMENT_CENTER
	_choices.add_theme_constant_override("separation", 10)
	add_child(_choices)


func go(id: String) -> void:
	if not _nodes.has(id):
		push_error("visual novel: unknown node '%s'" % id)
		_finish("The story ends.")
		return
	current_id = id
	var n: Dictionary = _nodes[id]
	var g := get_node_or_null("/root/AmerikaGame")
	if n.has("set_flag") and g != null:
		g.call("set_flag", str(n["set_flag"]))
	_set_bg(str(n.get("bg", "")))
	var who := str(n.get("speaker", ""))
	_name.text = who
	var ch: Dictionary = _characters.get(who, {})
	_name.add_theme_color_override("font_color", Color(str(ch.get("color", "#" + _accent.to_html(false)))))
	var tex_path := str(n.get("portrait", ch.get("texture", "")))
	_portrait.texture = load(tex_path) as Texture2D if tex_path != "" and ResourceLoader.exists(tex_path) else null
	var line := str(n.get("text", ""))
	_history.append("%s: %s" % [who, line])
	_text.text = line
	_text.visible_ratio = 0.0
	_typing = 0.0
	_clear_choices()
	if n.has("sfx") and g != null:
		g.call("play_sfx", str(n["sfx"]))
	if n.has("choices") and not (n["choices"] as Array).is_empty():
		_hint.text = ""
	else:
		_hint.text = "Enter / click to continue"


func _set_bg(spec: String) -> void:
	if spec == "":
		return
	if spec.begins_with("res://") and ResourceLoader.exists(spec):
		_bg_tex.texture = load(spec) as Texture2D
	else:
		_bg_tex.texture = null
		_bg.color = Color(spec)


func _clear_choices() -> void:
	choices_visible = false
	for c in _choices.get_children():
		c.queue_free()


func _show_choices() -> void:
	var g := get_node_or_null("/root/AmerikaGame")
	var n: Dictionary = _nodes[current_id]
	var i := 0
	for c in n.get("choices", []):
		var req := str(c.get("if_flag", ""))
		if req != "" and g != null and not bool(g.call("has_flag", req)):
			continue
		var b := Button.new()
		b.text = str(c.get("text", "..."))
		b.custom_minimum_size = Vector2(0, 46)
		b.add_theme_font_size_override("font_size", 22)
		b.pressed.connect(choose.bind(i))
		_choices.add_child(b)
		i += 1
	choices_visible = _choices.get_child_count() > 0


## Pick visible choice `index` (what the buttons call).
func choose(index: int) -> void:
	var g := get_node_or_null("/root/AmerikaGame")
	var n: Dictionary = _nodes[current_id]
	var visible_i := 0
	for c in n.get("choices", []):
		var req := str(c.get("if_flag", ""))
		if req != "" and g != null and not bool(g.call("has_flag", req)):
			continue
		if visible_i == index:
			if c.has("set_flag") and g != null:
				g.call("set_flag", str(c["set_flag"]))
			go(str(c.get("goto", "")))
			return
		visible_i += 1


## Advance: complete the typewriter, show choices, or move to the next node.
func advance() -> void:
	if finished or choices_visible:
		return
	if _text.visible_ratio < 1.0:
		_text.visible_ratio = 1.0
		return
	var n: Dictionary = _nodes.get(current_id, {})
	if not (n.get("choices", []) as Array).is_empty():
		_show_choices()
		return
	if bool(n.get("end", false)) or not n.has("next"):
		_finish(str(n.get("end_text", "The End")))
		return
	go(str(n["next"]))


func _finish(text: String) -> void:
	finished = true
	var g := get_node_or_null("/root/AmerikaGame")
	if g != null:
		g.call("win", text)
	_hint.text = "The End. Press Enter to start over."


func _process(delta: float) -> void:
	if _text.visible_ratio < 1.0:
		_typing += delta * 60.0
		_text.visible_characters = int(_typing)
	if not finished and not choices_visible and _text.visible_ratio >= 1.0:
		var n: Dictionary = _nodes.get(current_id, {})
		if not (n.get("choices", []) as Array).is_empty():
			_show_choices()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_accept") or (event is InputEventMouseButton and (event as InputEventMouseButton).pressed and (event as InputEventMouseButton).button_index == MOUSE_BUTTON_LEFT):
		advance()
