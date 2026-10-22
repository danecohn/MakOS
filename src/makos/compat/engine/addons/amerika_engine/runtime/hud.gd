extends CanvasLayer
## Heads-up display built in code: score, health pips, level name, message line and the win/lose overlay.
## Which elements show is controlled by `ui.hud` in res://amerika_game.json.

var _score: Label
var _level: Label
var _message: Label
var _pips: HBoxContainer
var _overlay: ColorRect
var _title: Label
var _hint: Label
var _msg_time: float = 0.0
var _accent: Color = Color("ff3d6e")
var _text: Color = Color("fff0cf")
var _panel: Color = Color("0e0810")
var _max_pips: int = 0


func _ready() -> void:
	layer = 10
	var g := get_node_or_null("/root/AmerikaGame")
	var elements: Array = ["score", "health", "level", "message"]
	if g != null:
		elements = g.call("cfg", "ui.hud", elements)
		_accent = Color(str(g.call("cfg", "theme.accent", "ff3d6e")))
		_text = Color(str(g.call("cfg", "theme.text", "fff0cf")))
		_panel = Color(str(g.call("cfg", "theme.panel", "0e0810")))
	var root := MarginContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for side in ["left", "top", "right", "bottom"]:
		root.add_theme_constant_override("margin_" + side, 14)
	add_child(root)
	var top := HBoxContainer.new()
	top.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	top.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(top)
	_score = _label("SCORE 0", 22)
	_score.visible = "score" in elements
	top.add_child(_score)
	_pips = HBoxContainer.new()
	_pips.add_theme_constant_override("separation", 4)
	_pips.visible = "health" in elements
	_pips.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	top.add_child(_pips)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(spacer)
	_level = _label("", 18)
	_level.visible = "level" in elements
	top.add_child(_level)
	_message = _label("", 20)
	_message.visible = "message" in elements
	_message.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	_message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_message.size_flags_vertical = Control.SIZE_SHRINK_END
	_message.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root.add_child(_message)
	_overlay = ColorRect.new()
	_overlay.color = Color(_panel, 0.82)
	_overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	_overlay.visible = false
	add_child(_overlay)
	var box := VBoxContainer.new()
	box.set_anchors_preset(Control.PRESET_FULL_RECT)
	box.alignment = BoxContainer.ALIGNMENT_CENTER
	_overlay.add_child(box)
	_title = _label("", 54)
	_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(_title)
	_hint = _label("Press Enter to continue", 22)
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(_hint)
	if g != null:
		g.connect("score_changed", _on_score)
		g.connect("health_changed", _on_health)
		g.connect("message", _on_message)
		g.connect("state_changed", _on_state)
		g.connect("level_started", _on_level)
		_on_score(int(g.get("score")))
		if int(g.get("max_health")) > 0:
			_on_health(int(g.get("health")), int(g.get("max_health")))
		_on_level(str(g.get("level").get("level_name")) if g.get("level") != null else "")
		var title: String = str(g.call("cfg", "ui.title", ""))
		if title != "" and g.get("level") != null and int(g.call("level_index")) == 0:
			_on_message("", title)


func _label(text: String, size: int) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", _text)
	l.add_theme_color_override("font_outline_color", _panel)
	l.add_theme_constant_override("outline_size", 6)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return l


func _on_score(value: int) -> void:
	_score.text = "SCORE %d" % value


func _on_health(current: int, maximum: int) -> void:
	if maximum != _max_pips:
		for c in _pips.get_children():
			c.queue_free()
		_max_pips = maximum
		for i in range(maximum):
			var pip := ColorRect.new()
			pip.custom_minimum_size = Vector2(18, 18)
			_pips.add_child(pip)
	for i in range(_pips.get_child_count()):
		var pip := _pips.get_child(i) as ColorRect
		if pip != null:
			pip.color = _accent if i < current else Color(_text, 0.18)


func _on_level(level_name: String) -> void:
	_level.text = level_name.replace("_", " ").to_upper()


func _on_message(speaker: String, text: String) -> void:
	_message.text = ("%s: %s" % [speaker, text]) if speaker != "" else text
	_msg_time = 3.5


func _on_state(state: String, text: String) -> void:
	_overlay.visible = true
	_title.text = text
	_title.add_theme_color_override("font_color", _accent if state == "lost" else _text)
	var g := get_node_or_null("/root/AmerikaGame")
	var next: bool = state == "won" and g != null and bool(g.call("has_next_level"))
	_hint.text = "Press Enter for the next level" if next else "Press Enter to play again"


func _process(delta: float) -> void:
	if _msg_time > 0.0:
		_msg_time -= delta
		if _msg_time <= 0.0:
			_message.text = ""
