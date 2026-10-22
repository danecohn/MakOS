extends VBoxContainer
## The "Amerika" dock: chat history, model choice, Review-before-run, Stop, per-request Undo/Redo, quick actions.

var ai: Node
var tools: RefCounted
var _log: RichTextLabel
var _input: TextEdit
var _send: Button
var _stop: Button
var _undo: Button
var _redo: Button
var _model: OptionButton
var _review: CheckBox
var _status: Label
var _approval: PanelContainer
var _approval_text: RichTextLabel
var _approval_id: String = ""
var _undone: Array = []


func setup(p_ai: Node, p_tools: RefCounted) -> void:
	ai = p_ai
	tools = p_tools
	name = "Amerika"
	custom_minimum_size = Vector2(300, 400)
	var top := HBoxContainer.new()
	add_child(top)
	_model = OptionButton.new()
	_model.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_model.tooltip_text = "Model"
	top.add_child(_model)
	_review = CheckBox.new()
	_review.text = "Review"
	_review.tooltip_text = "Review before run: ask before the assistant saves scripts it wrote"
	_review.button_pressed = true
	_review.toggled.connect(func(on: bool) -> void: ai.review = on; _save_settings())
	top.add_child(_review)
	_log = RichTextLabel.new()
	_log.bbcode_enabled = true
	_log.scroll_following = true
	_log.selection_enabled = true
	_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(_log)
	_approval = PanelContainer.new()
	_approval.visible = false
	var av := VBoxContainer.new()
	_approval.add_child(av)
	_approval_text = RichTextLabel.new()
	_approval_text.bbcode_enabled = true
	_approval_text.custom_minimum_size = Vector2(0, 160)
	av.add_child(_approval_text)
	var ab := HBoxContainer.new()
	av.add_child(ab)
	var yes := Button.new()
	yes.text = "Run it"
	yes.pressed.connect(_answer.bind(true))
	ab.add_child(yes)
	var no := Button.new()
	no.text = "Decline"
	no.pressed.connect(_answer.bind(false))
	ab.add_child(no)
	add_child(_approval)
	_status = Label.new()
	_status.text = ""
	add_child(_status)
	_input = TextEdit.new()
	_input.custom_minimum_size = Vector2(0, 70)
	_input.placeholder_text = "Describe your game or what to change..."
	_input.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	add_child(_input)
	var bar := HBoxContainer.new()
	add_child(bar)
	_send = _btn(bar, "Send", _on_send)
	_stop = _btn(bar, "Stop", func() -> void: ai.stop())
	_stop.disabled = true
	_undo = _btn(bar, "Undo request", _on_undo)
	_redo = _btn(bar, "Redo", _on_redo)
	_btn(bar, "Assemble", func() -> void: _quick("Assemble the recipe and run it for 300 frames; fix any errors."))
	_btn(bar, "New chat", func() -> void: ai.clear_chat(); _log.clear(); _say("[color=gray]New conversation.[/color]"))
	ai.assistant_text.connect(func(t: String) -> void: _say("[b]Amerika:[/b] " + _esc(t)))
	ai.tool_started.connect(func(_id: String, n: String, i: Dictionary) -> void: _say("[color=#ffb02e]> %s[/color] %s" % [n, _esc(JSON.stringify(i).left(160))]))
	ai.tool_finished.connect(func(_id: String, n: String, s: String, ok: bool) -> void: _say("[color=%s]  %s: %s[/color]" % ["#3dffb0" if ok else "#ff3d6e", "done" if ok else "failed", _esc(s)]))
	ai.status.connect(func(t: String) -> void: _status.text = t)
	ai.busy_changed.connect(_on_busy)
	ai.approval_needed.connect(_on_approval)
	ai.finished.connect(_on_finished)
	_load_settings()
	_replay()
	_refresh_models()
	_say("[color=gray]Describe the game you want. Every request can be undone with Undo request.[/color]")


func _btn(parent: Control, text: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.pressed.connect(cb)
	parent.add_child(b)
	return b


func _esc(t: String) -> String:
	return t.replace("[", "[lb]")


func _say(bb: String) -> void:
	_log.append_text(bb + "\n")


func _refresh_models() -> void:
	var models: Array = await ai.fetch_models()
	_model.clear()
	for m in models:
		_model.add_item(str(m))
	var idx := models.find(ai.model)
	_model.select(maxi(idx, 0))
	ai.model = str(models[maxi(idx, 0)])
	_model.item_selected.connect(func(i: int) -> void: ai.model = _model.get_item_text(i); _save_settings())


func _replay() -> void:
	ai.load_chat()
	for m in ai.messages:
		if m["content"] is Array:
			for b in m["content"]:
				if b.get("type") == "text":
					_say(("[b]You:[/b] " if m["role"] == "user" else "[b]Amerika:[/b] ") + _esc(str(b["text"])))


func _on_send() -> void:
	var t := _input.text.strip_edges()
	if t == "" or ai.busy:
		return
	_input.text = ""
	_undone = []
	_say("[b]You:[/b] " + _esc(t))
	ai.run_prompt(t)


func _quick(t: String) -> void:
	if ai.busy:
		return
	_say("[b]You:[/b] " + _esc(t))
	ai.run_prompt(t)


func _on_busy(b: bool) -> void:
	_send.disabled = b
	_stop.disabled = not b


func _on_finished(r: Dictionary) -> void:
	if not r.get("ok", false):
		_say("[color=#ff3d6e]%s[/color]" % _esc(str(r.get("error", "failed"))))


func _on_approval(id: String, n: String, input: Dictionary) -> void:
	_approval_id = id
	var code := str(input.get("code", input.get("content", "")))
	if input.has("edits"):
		code = JSON.stringify(input["edits"], "  ")
	_approval_text.text = "[b]%s[/b] %s\n[code]%s[/code]" % [n, _esc(str(input.get("path", ""))), _esc(code.left(4000))]
	_approval.visible = true


func _answer(ok: bool) -> void:
	_approval.visible = false
	ai.resolve_approval(_approval_id, ok)


func _on_undo() -> void:
	var s: Dictionary = tools.history.last_session()
	if s.is_empty():
		return
	var r: Dictionary = tools.history.restore(str(s["id"]), false)
	_undone.append(s["id"])
	_say("[color=gray]Undid: %s (%d files)[/color]" % [_esc(str(s.get("label", ""))), (r.get("restored", []) as Array).size()])


func _on_redo() -> void:
	if _undone.is_empty():
		return
	var id: String = _undone.pop_back()
	tools.history.restore(id, true)
	_say("[color=gray]Redid a request.[/color]")


func _save_settings() -> void:
	DirAccess.make_dir_recursive_absolute("res://.amerika")
	var f := FileAccess.open("res://.amerika/settings.json", FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"model": ai.model, "review": ai.review}))


func _load_settings() -> void:
	if FileAccess.file_exists("res://.amerika/settings.json"):
		var s: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://.amerika/settings.json"))
		if s is Dictionary:
			ai.model = str(s.get("model", ai.model))
			ai.review = bool(s.get("review", true))
			_review.button_pressed = ai.review
