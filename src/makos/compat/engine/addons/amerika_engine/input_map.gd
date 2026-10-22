extends RefCounted
## Writes input actions into the project settings (the [input] section of project.godot).
## Key names are Godot key strings ("A", "Left", "Space", "Escape", "Shift") or "Mouse:Left|Right|Middle".


func event_for(key_name: String) -> InputEvent:
	if key_name.begins_with("Mouse:"):
		var mb := InputEventMouseButton.new()
		match key_name.substr(6):
			"Left":
				mb.button_index = MOUSE_BUTTON_LEFT
			"Right":
				mb.button_index = MOUSE_BUTTON_RIGHT
			"Middle":
				mb.button_index = MOUSE_BUTTON_MIDDLE
			_:
				return null
		return mb
	var code := OS.find_keycode_from_string(key_name)
	if code == KEY_NONE:
		return null
	var k := InputEventKey.new()
	k.physical_keycode = code
	return k


## actions: {action_name: [key names]}. An empty list removes the action. Returns warnings for unknown keys.
func apply(actions: Dictionary, save: bool = true) -> Dictionary:
	var warnings: Array = []
	var applied: Array = []
	for a in actions.keys():
		if str(a).begins_with("ui_") or not str(a).is_valid_identifier():
			warnings.append("action '%s' skipped (ui_* actions and non-identifiers are not changed)" % a)
			continue
		var setting := "input/" + str(a)
		var evs: Array = []
		for key_name in actions[a]:
			var ev := event_for(str(key_name))
			if ev == null:
				warnings.append("unknown key '%s' for action '%s' ignored" % [key_name, a])
			else:
				evs.append(ev)
		if evs.is_empty():
			if ProjectSettings.has_setting(setting):
				ProjectSettings.clear(setting)
		else:
			ProjectSettings.set_setting(setting, {"deadzone": 0.2, "events": evs})
			applied.append(str(a))
		if InputMap.has_action(str(a)):
			InputMap.erase_action(str(a))
		if not evs.is_empty():
			InputMap.add_action(str(a))
			for ev in evs:
				InputMap.action_add_event(str(a), ev)
	var err := OK
	if save:
		err = ProjectSettings.save()
	return {"applied": applied, "warnings": warnings, "error": error_string(err) if err != OK else ""}
